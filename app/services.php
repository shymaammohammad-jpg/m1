<?php
function period(int $id,bool $draft=false):array{$p=owned('exam_periods',$id);if($draft&&$p['status']!=='draft')throw new RuntimeException('الخريطة معتمدة ومقفلة. يفتحها المدير للمراجعة أولًا.');return $p;}
function candidates(array $p):array {
 $r=rows('SELECT c.id AS candidate_id,c.student_id AS id,c.subject_id,c.carry_note,s.name,s.code,s.department_id,s.stage_id,s.year_id,s.active,s.shift,s.section_name,s.needs_access,d.name AS department,t.name AS stage,b.name AS subject FROM exam_candidates c JOIN students s ON s.id=c.student_id JOIN departments d ON d.id=s.department_id JOIN stages t ON t.id=s.stage_id JOIN subjects b ON b.id=c.subject_id WHERE c.institution_id=? AND c.period_id=? ORDER BY s.id',[inst(),$p['id']]);
 foreach($r as &$s){$s['id']=(int)$s['id'];$s['group']=(string)$s[$p['grouping']==='department'?'department_id':'subject_id'];}unset($s);return $r;
}
function seat_rows(array $p):array {
 return rows('SELECT a.id AS assignment_id,a.student_id,a.seat_id,s.code,s.name,s.needs_access,s.department_id,s.stage_id,d.name AS department,t.name AS stage,s.shift,s.section_name,b.name AS subject,c.subject_id,r.id AS room_id,r.code AS room_code,r.name AS room_name,r.building,r.floor_name,r.rows_count,r.cols_count,r.board,r.entrance,r.capacity,r.status AS room_status,r.required_monitors,q.label,q.row_no,q.col_no,q.state,q.accessible FROM seating_assignments a JOIN students s ON s.id=a.student_id JOIN departments d ON d.id=s.department_id JOIN stages t ON t.id=s.stage_id JOIN exam_candidates c ON c.period_id=a.period_id AND c.student_id=a.student_id JOIN subjects b ON b.id=c.subject_id JOIN room_seats q ON q.id=a.seat_id JOIN rooms r ON r.id=q.room_id WHERE a.institution_id=? AND a.period_id=? ORDER BY r.id,q.row_no,q.col_no',[inst(),$p['id']]);
}
function monitor_rows(array $p):array{return rows('SELECT a.*,i.name,i.academic_title,i.duty,r.code AS room_code,r.name AS room_name,r.building FROM invigilation_assignments a JOIN invigilators i ON i.id=a.invigilator_id JOIN rooms r ON r.id=a.room_id WHERE a.institution_id=? AND a.period_id=? ORDER BY r.id,a.role,i.name',[inst(),$p['id']]);}
function occupied_rooms(array $p):array{return rows('SELECT DISTINCT r.* FROM rooms r JOIN room_seats s ON s.room_id=r.id JOIN seating_assignments a ON a.seat_id=s.id WHERE a.institution_id=? AND a.period_id=? ORDER BY r.id',[inst(),$p['id']]);}
function room_conflicts(array $p):array{return array_map('intval',array_column(rows('SELECT DISTINCT s.room_id FROM seating_assignments a JOIN room_seats s ON s.id=a.seat_id JOIN exam_periods o ON o.id=a.period_id WHERE a.institution_id=? AND o.id<>? AND o.starts_at<? AND o.ends_at>?',[inst(),$p['id'],$p['ends_at'],$p['starts_at']]),'room_id'));}
function candidate_conflicts(array $p):array {
 return rows('SELECT s.name,s.code,o.name AS other_period,o.starts_at FROM exam_candidates c JOIN exam_candidates x ON x.student_id=c.student_id AND x.period_id<>c.period_id JOIN exam_periods o ON o.id=x.period_id JOIN students s ON s.id=c.student_id WHERE c.institution_id=? AND c.period_id=? AND o.starts_at<? AND o.ends_at>?',[inst(),$p['id'],$p['ends_at'],$p['starts_at']]);
}
function monitor_available(array $p,int $id):bool {
 $i=owned('invigilators',$id);if(!$i['active'])return false;
 if(rows('SELECT id FROM invigilator_availability WHERE institution_id=? AND invigilator_id=? AND starts_at<? AND ends_at>?',[inst(),$id,$p['ends_at'],$p['starts_at']]))return false;
 return !rows('SELECT a.id FROM invigilation_assignments a JOIN exam_periods o ON o.id=a.period_id WHERE a.institution_id=? AND a.invigilator_id=? AND o.id<>? AND o.starts_at<? AND o.ends_at>?',[inst(),$id,$p['id'],$p['ends_at'],$p['starts_at']]);
}
function map_issues(array $p,bool $withMonitors=true):array {
 $errors=[];$warnings=[];$c=candidates($p);$a=seat_rows($p);$candidateIds=array_column($c,'id');$assignedIds=array_map('intval',array_column($a,'student_id'));
 $raw=rows('SELECT student_id,seat_id FROM seating_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);if(count($raw)!==count($a)||array_diff(array_map('intval',array_column($raw,'student_id')),$candidateIds))$errors[]='توجد مقاعد مسندة إلى أسماء غير مرشحة للمادة في الفترة.';
 if(!$c)$errors[]='قائمة المرشحين فارغة.';
 if(count($a)!==count($c)||array_diff($candidateIds,$assignedIds)||array_diff($assignedIds,$candidateIds))$errors[]='لم يخصص مقعد واحد لكل طالب مرشح.';
 foreach($c as $s){$subject=owned('subjects',(int)$s['subject_id']);if((int)$subject['department_id']!==(int)$s['department_id']||((int)$subject['stage_id']!==(int)$s['stage_id']&&trim($s['carry_note']??'')===''))$errors[]='ترشيح غير موثق للمادة: '.$s['code'];}
 foreach($c as $s)if(!$s['active']||(int)$s['year_id']!==(int)$p['year_id'])$errors[]='طالب غير نشط أو من عام آخر: '.$s['code'];
 foreach(candidate_conflicts($p) as $x)$errors[]='تعارض طالب '.$x['code'].' مع '.$x['other_period'];
 $blocked=room_conflicts($p);$counts=[];$bySeat=[];$positions=[];$roomIds=array_map('intval',array_column(rows('SELECT room_id FROM period_rooms WHERE period_id=? AND institution_id=?',[$p['id'],inst()]),'room_id'));
 foreach($a as $s){$room=(int)$s['room_id'];$counts[$room]=($counts[$room]??0)+1;$bySeat[$s['seat_id']]=$s;$positions[$room.':'.$s['row_no'].':'.$s['col_no']]=$s;
  if($s['state']!=='active'||!in_array($s['room_status'],['available','reserve'],true))$errors[]='مقعد غير صالح أو قاعة غير متاحة: '.$s['room_code'].' / '.$s['label'];
  if(in_array($room,$blocked,true))$errors[]='القاعة '.$s['room_code'].' مستخدمة في فترة متداخلة.';
  if($roomIds&&!in_array($room,$roomIds,true))$errors[]='قاعة خارج القاعات المختارة للفترة.';
  if($s['needs_access']&&!$s['accessible'])$errors[]='المقعد لا يحقق حاجة الوصول للطالب '.$s['code'];
  if($counts[$room]>(int)$s['capacity'])$errors[]='تجاوز السعة المسموحة للقاعة '.$s['room_code'];
 }
 $adj=0;if($p['adjacency']!=='none')foreach($a as $s){$deltas=$p['adjacency']==='horizontal'?[[0,1]]:[[0,1],[1,0]];foreach($deltas as [$dr,$dc]){$near=$positions[$s['room_id'].':'.($s['row_no']+$dr).':'.($s['col_no']+$dc)]??null;if($near&&$near[$p['grouping']==='department'?'department_id':'subject_id']===$s[$p['grouping']==='department'?'department_id':'subject_id'])$adj++;}}
 if($adj){if($p['strict_separation'])$errors[]='الفصل الإلزامي مخالف في '.$adj.' تجاور.';else $warnings[]='يوجد '.$adj.' تجاور للمجموعة نفسها؛ الفصل تفضيلي.';}
 if($withMonitors){$monitors=monitor_rows($p);$perRoom=[];$chief=[];
  foreach($monitors as $m){$rid=(int)$m['room_id'];$perRoom[$rid]=($perRoom[$rid]??0)+1;if($m['role']==='chief'){$chief[$rid]=($chief[$rid]??0)+1;if($m['duty']==='observer')$errors[]='مراقب غير مؤهل لرئاسة القاعة.';}if(!isset($counts[$rid]))$errors[]='تكليف مراقب لقاعة غير مشغولة.';if(!monitor_available($p,(int)$m['invigilator_id']))$errors[]='تعارض أو استثناء مراقب: '.$m['name'];}
  foreach(occupied_rooms($p) as $r)if(($perRoom[$r['id']]??0)!==(int)$r['required_monitors']||($chief[$r['id']]??0)!==1)$errors[]='عدد المراقبين أو رئيس القاعة غير مكتمل للقاعة '.$r['code'];
 }
 return ['errors'=>array_values(array_unique($errors)),'warnings'=>array_values(array_unique($warnings))];
}
function snapshot(array $p):array {
 $rooms=occupied_rooms($p);$seats=[];foreach($rooms as $r)$seats[$r['id']]=rows('SELECT * FROM room_seats WHERE room_id=? AND institution_id=? ORDER BY row_no,col_no',[$r['id'],inst()]);
 $capacity=[];$ownCounts=array_count_values(array_column(seat_rows($p),'room_id'));$blocked=room_conflicts($p);foreach(rows("SELECT r.*,COUNT(s.id) AS physical_seats,SUM(s.state='active') AS active_seats FROM rooms r LEFT JOIN room_seats s ON s.room_id=r.id WHERE r.institution_id=? GROUP BY r.id ORDER BY r.code",[inst()]) as $r){$r['used']=$ownCounts[$r['id']]??0;$r['remaining']=($r['status']==='booked'||in_array((int)$r['id'],$blocked,true))?0:max(0,min((int)$r['capacity'],(int)$r['active_seats'])-$r['used']);$capacity[]=$r;}
 return ['capacity'=>$capacity,'period'=>$p,'institution'=>rows('SELECT * FROM institutions WHERE id=?',[inst()])[0],'year'=>owned('academic_years',(int)$p['year_id']),'rooms'=>$rooms,'seats'=>$seats,'students'=>seat_rows($p),'monitors'=>monitor_rows($p),'issues'=>map_issues($p),'created_at'=>date('c')];
}
function version(array $p,string $action):void {
 $p=period((int)$p['id']);$p['approved_snapshot']=null;$revision=(int)$p['revision']+1;$s=snapshot($p);$s['period']['revision']=$revision;
 run('INSERT INTO map_versions(institution_id,period_id,revision,action,snapshot,created_by) VALUES(?,?,?,?,?,?)',[inst(),$p['id'],$revision,$action,json_encode($s,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR),$_SESSION['uid']]);
 run('UPDATE exam_periods SET revision=? WHERE id=? AND institution_id=?',[$revision,$p['id'],inst()]);audit($action,'الفترة '.$p['id'].' / النسخة '.$revision);
}
function ensure_no_maps(array $p):void {if(rows('SELECT id FROM seating_assignments WHERE period_id=? AND institution_id=?',[$p['id'],inst()]))throw new RuntimeException('أفرغ الخريطة المسودة قبل تغيير المرشحين أو إعدادات الفترة. تُحفظ نسخة سابقة في السجل.');}
function add_candidate(array $p,int $studentId,int $subjectId,string $carryNote=''):void {
 $s=owned('students',$studentId);$b=owned('subjects',$subjectId);
 if(!$s['active']||(int)$s['year_id']!==(int)$p['year_id']||((int)$s['stage_id']!==(int)$b['stage_id']&&$carryNote==='')||(int)$s['department_id']!==(int)$b['department_id'])throw new RuntimeException('الطالب غير مؤهل للمادة أو لا ينتمي إلى عام الفترة.');
 if(rows('SELECT c.id FROM exam_candidates c JOIN exam_periods o ON o.id=c.period_id WHERE c.institution_id=? AND c.student_id=? AND o.starts_at<? AND o.ends_at>?',[inst(),$studentId,$p['ends_at'],$p['starts_at']]))throw new RuntimeException('الطالب '.$s['code'].' مرشح بالفعل لامتحان في فترة متداخلة.');
 run('INSERT INTO exam_candidates(institution_id,period_id,student_id,subject_id,carry_note) VALUES(?,?,?,?,?)',[inst(),$p['id'],$studentId,$subjectId,$carryNote]);
}
function generate_students(array $p):void {
 if(candidate_conflicts($p))throw new RuntimeException('تعارضات طلبة؛ راجع تقرير التعارضات.');$students=candidates($p);foreach($students as $s)if(!$s['active'])throw new RuntimeException('توجد أسماء غير نشطة ضمن المرشحين.');
 $chosen=array_map('intval',array_column(rows('SELECT room_id FROM period_rooms WHERE institution_id=? AND period_id=?',[inst(),$p['id']]),'room_id'));$blocked=room_conflicts($p);
 $rooms=array_values(array_filter(rows("SELECT * FROM rooms WHERE institution_id=? AND status IN ('available','reserve') ORDER BY id",[inst()]),fn($r)=>(!$chosen||in_array((int)$r['id'],$chosen,true))&&!in_array((int)$r['id'],$blocked,true)));
 foreach($rooms as &$r){$r['id']=(int)$r['id'];$r['capacity']=(int)$r['capacity'];}unset($r);
 $seats=rows('SELECT * FROM room_seats WHERE institution_id=? ORDER BY id',[inst()]);foreach($seats as &$s){foreach(['id','room_id','row_no','col_no'] as $k)$s[$k]=(int)$s[$k];}unset($s);
 $solution=(new SeatingSolver())->solve($students,$rooms,$seats,$p['adjacency'],(bool)$p['strict_separation']);
 run('DELETE FROM invigilation_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);run('DELETE FROM seating_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);
 foreach($solution as $a)run('INSERT INTO seating_assignments(institution_id,period_id,student_id,seat_id) VALUES(?,?,?,?)',[inst(),$p['id'],$a['student_id'],$a['seat_id']]);
 $issues=map_issues($p,false);if($issues['errors'])throw new RuntimeException(implode(' / ',$issues['errors']));version($p,'توليد خريطة الطلبة');
}
function generate_monitors(array $p):void {
 if(map_issues($p,false)['errors'])throw new RuntimeException('أكمل خريطة طلبة صالحة أولًا.');$people=rows('SELECT * FROM invigilators WHERE institution_id=? AND active=1 ORDER BY id',[inst()]);$duration=(int)((strtotime($p['ends_at'])-strtotime($p['starts_at']))/60);
 foreach($people as &$person){$person['id']=(int)$person['id'];$person['work_minutes']=(int)(rows('SELECT COALESCE(SUM(TIMESTAMPDIFF(MINUTE,o.starts_at,o.ends_at)),0) AS minutes FROM invigilation_assignments a JOIN exam_periods o ON o.id=a.period_id WHERE a.institution_id=? AND a.invigilator_id=? AND a.period_id<>?',[inst(),$person['id'],$p['id']])[0]['minutes']);}unset($person);
 $people=array_values(array_filter($people,fn($i)=>monitor_available($p,(int)$i['id'])));$solution=solve_monitors($people,occupied_rooms($p),$duration);
 run('DELETE FROM invigilation_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);foreach($solution as $a)run('INSERT INTO invigilation_assignments(institution_id,period_id,room_id,invigilator_id,role) VALUES(?,?,?,?,?)',[inst(),$p['id'],$a['room_id'],$a['invigilator_id'],$a['role']]);
 $issues=map_issues($p);if($issues['errors'])throw new RuntimeException(implode(' / ',$issues['errors']));version($p,'توزيع المراقبين');
}
const BACKUP_TABLES=['academic_years','departments','stages','subjects','students','rooms','room_seats','exam_periods','period_rooms','exam_candidates','seating_assignments','invigilators','invigilator_availability','invigilation_assignments','map_versions'];
function export_backup():array{$data=['format'=>'maqad-1','institution_id'=>inst(),'institution'=>rows('SELECT * FROM institutions WHERE id=?',[inst()])[0],'tables'=>[]];foreach(BACKUP_TABLES as $table)$data['tables'][$table]=rows("SELECT * FROM $table WHERE institution_id=?",[inst()]);$payload=json_encode($data,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);$envelope=['payload'=>$payload,'signature'=>hash_hmac('sha256',$payload,secret_key())];if(strlen(json_encode($envelope,JSON_UNESCAPED_UNICODE))>20*1024*1024)throw new RuntimeException('حجم النسخة يتجاوز حد الاستعادة 20 ميغابايت؛ استخدم تصدير قاعدة كاملة عبر phpMyAdmin.');return $envelope;}
function restore_backup(array $file):void {
 $envelope=json_decode(file_get_contents($file['tmp_name']),true,512,JSON_THROW_ON_ERROR);$payload=$envelope['payload']??'';
 if(!is_string($payload)||!hash_equals(hash_hmac('sha256',$payload,secret_key()),(string)($envelope['signature']??'')))throw new RuntimeException('بصمة النسخة غير مطابقة لمفتاح هذه النسخة من مقعد.');
 $data=json_decode($payload,true,512,JSON_THROW_ON_ERROR);if(($data['format']??'')!=='maqad-1'||(int)($data['institution_id']??0)!==inst()||array_keys($data['tables']??[])!==BACKUP_TABLES)throw new RuntimeException('نسخة غير متوافقة أو لمؤسسة أخرى.');
 foreach(array_reverse(BACKUP_TABLES) as $t)run("DELETE FROM $t WHERE institution_id=?",[inst()]);
 foreach(BACKUP_TABLES as $t){$columns=array_column(rows("SHOW COLUMNS FROM $t"),'Field');foreach($data['tables'][$t] as $r){if((int)($r['institution_id']??0)!==inst()||array_diff(array_keys($r),$columns))throw new RuntimeException('نطاق أو بنية سجل غير صحيح في النسخة.');$keys=array_keys($r);run("INSERT INTO $t (`".implode('`,`',$keys).'`) VALUES('.implode(',',array_fill(0,count($keys),'?')).')',array_values($r));}}
 run('UPDATE institutions SET name=?,university=? WHERE id=?',[$data['institution']['name'],$data['institution']['university'],inst()]);audit('استعادة نسخة احتياطية','استعادة بيانات المؤسسة دون حسابات المستخدمين أو سجل التدقيق.');
}
