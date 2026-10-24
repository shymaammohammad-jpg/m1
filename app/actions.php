<?php
function save_entity(string $kind,array $post):int {
 $tables=['department'=>'departments','stage'=>'stages','year'=>'academic_years','subject'=>'subjects','student'=>'students','room'=>'rooms','invigilator'=>'invigilators'];if(!isset($tables[$kind]))throw new RuntimeException('نوع غير معروف.');$table=$tables[$kind];$id=(int)($post['id']??0);$old=$id?owned($table,$id):null;$v=[];
 if(in_array($kind,['department','stage','year','subject','student','room','invigilator'],true))$v['name']=txt($post['name']??'');
 if(in_array($kind,['stage','subject','student'],true)){$v['department_id']=intv($post['department_id']??0);owned('departments',$v['department_id']);}
 if(in_array($kind,['subject','student'],true)){$v['stage_id']=intv($post['stage_id']??0);$stage=owned('stages',$v['stage_id']);if((int)$stage['department_id']!==$v['department_id'])throw new RuntimeException('المرحلة لا تتبع القسم المختار.');}
 if($kind==='stage'&&$old&&$v['department_id']!==(int)$old['department_id']&&(rows('SELECT id FROM subjects WHERE institution_id=? AND stage_id=?',[inst(),$id])||rows('SELECT id FROM students WHERE institution_id=? AND stage_id=?',[inst(),$id])))throw new RuntimeException('المرحلة مرتبطة بمواد أو طلبة؛ لا يمكن نقلها إلى قسم آخر.');
 if($kind==='subject'&&$old&&($v['department_id']!==(int)$old['department_id']||$v['stage_id']!==(int)$old['stage_id'])&&rows('SELECT id FROM exam_candidates WHERE institution_id=? AND subject_id=?',[inst(),$id]))throw new RuntimeException('المادة مرتبطة بترشيحات؛ لا يمكن تغيير قسمها أو مرحلتها.');
 if($kind==='student'){
  $v+=['year_id'=>$old?(int)$old['year_id']:year_id(),'code'=>txt($post['code']??'',60),'shift'=>enumv($post['shift']??'',['صباحي','مسائي']),'section_name'=>txt($post['section_name']??'',80,false),'needs_access'=>isset($post['needs_access'])?1:0,'active'=>isset($post['active'])?1:0];
  if($old && rows("SELECT c.id FROM exam_candidates c JOIN exam_periods p ON p.id=c.period_id WHERE c.institution_id=? AND c.student_id=? AND (p.status='draft' OR p.ends_at>=CURRENT_TIMESTAMP)",[inst(),$id]) && ($v['department_id']!==(int)$old['department_id']||$v['stage_id']!==(int)$old['stage_id']||$v['active']!==(int)$old['active']||$v['needs_access']!==(int)$old['needs_access']))throw new RuntimeException('للطالب ترشيحات امتحانية؛ أزلها من المسودات أولًا قبل تغيير الأهلية أو احتياجات الوصول.');
 }
 if($kind==='room'){
  $v+=['code'=>txt($post['code']??'',50),'building'=>txt($post['building']??'',120),'floor_name'=>txt($post['floor_name']??'',40),'rows_count'=>intv($post['rows_count']??0,1,30),'cols_count'=>intv($post['cols_count']??0,1,20),'capacity'=>intv($post['capacity']??0,1,600),'status'=>enumv($post['status']??'',['available','reserve','booked']),'board'=>enumv($post['board']??'',['north','south']),'entrance'=>txt($post['entrance']??'',100,false),'required_monitors'=>intv($post['required_monitors']??0,1,10)];
  if($v['capacity']>$v['rows_count']*$v['cols_count'])throw new RuntimeException('السعة تتجاوز عدد المواقع الهندسية.');
  if($old && rows('SELECT a.id FROM seating_assignments a JOIN room_seats s ON s.id=a.seat_id WHERE a.institution_id=? AND s.room_id=?',[inst(),$id]))throw new RuntimeException('القاعة مستخدمة في خريطة محفوظة؛ لا تغيّر هندستها أو سعتها. أنشئ قاعة جديدة للتعديل الهيكلي.');
 }
 if($kind==='invigilator'){
  $v+=['academic_title'=>txt($post['academic_title']??'',100),'department_id'=>!empty($post['department_id'])?intv($post['department_id']):null,'duty'=>enumv($post['duty']??'',['any','chief','observer']),'baseline_minutes'=>intv($post['baseline_minutes']??0,0,1000000),'active'=>isset($post['active'])?1:0];if($v['department_id'])owned('departments',$v['department_id']);
  if($old&&$v['duty']==='observer'&&rows("SELECT a.id FROM invigilation_assignments a JOIN exam_periods p ON p.id=a.period_id WHERE a.institution_id=? AND a.invigilator_id=? AND a.role='chief' AND p.ends_at>=?",[inst(),$id,date('Y-m-d H:i:s')]))throw new RuntimeException('للمراقب تكليف رئاسة قائم؛ استبدله قبل تغيير أهليته.');
  if($old && !$v['active'] && rows('SELECT a.id FROM invigilation_assignments a JOIN exam_periods p ON p.id=a.period_id WHERE a.institution_id=? AND a.invigilator_id=? AND p.ends_at>=?',[inst(),$id,date('Y-m-d H:i:s')]))throw new RuntimeException('للمراقب تكليفات حالية أو قادمة؛ استبدلها قبل تعطيله.');
 }
 if($id){$keys=array_keys($v);run("UPDATE $table SET ".implode(',',array_map(fn($k)=>"`$k`=?",$keys)).' WHERE id=? AND institution_id=?',[...array_values($v),$id,inst()]);}
 else{$v=['institution_id'=>inst()]+$v;$keys=array_keys($v);run("INSERT INTO $table (".'`'.implode('`,`',$keys).'`'.') VALUES('.implode(',',array_fill(0,count($v),'?')).')',array_values($v));$id=(int)db()->lastInsertId();}
 if($kind==='room'){
  if($old)run('DELETE FROM room_seats WHERE room_id=? AND institution_id=?',[$id,inst()]);
  for($r=1;$r<=$v['rows_count'];$r++)for($c=1;$c<=$v['cols_count'];$c++)run('INSERT INTO room_seats(institution_id,room_id,row_no,col_no,label) VALUES(?,?,?,?,?)',[inst(),$id,$r,$c,(string)(($r-1)*$v['cols_count']+$c)]);
 }
 audit($old?'تعديل '.$kind:'إضافة '.$kind,(string)$id);return $id;
}
function handle_action(string $action,array $post):array {
 if($action==='save'){$kind=$post['kind']??'';$id=save_entity($kind,$post);flash('تم حفظ البيانات.');return [$kind==='room'?'room':(in_array($kind,['department','stage','year','subject'],true)?'structure':($kind==='student'?'students':'invigilators')),$kind==='room'?['id'=>$id]:[]];}
 if($action==='delete'){
  $table=enumv($post['table']??'',['departments','stages','academic_years','subjects','students','rooms','invigilators','invigilator_availability']);$id=intv($post['id']??0);owned($table,$id);
  if($table==='academic_years'&&(int)rows('SELECT COUNT(*) AS n FROM academic_years WHERE institution_id=?',[inst()])[0]['n']<=1)throw new RuntimeException('أبقِ عامًا دراسيًا واحدًا على الأقل.');
  if($table==='rooms')run('DELETE FROM room_seats WHERE institution_id=? AND room_id=?',[inst(),$id]);run("DELETE FROM $table WHERE id=? AND institution_id=?",[$id,inst()]);audit('حذف آمن '.$table,(string)$id);flash('تم حذف السجل غير المرتبط.');return [in_array($table,['departments','stages','academic_years','subjects'],true)?'structure':($table==='invigilator_availability'?'invigilators':$table),[]];
 }
 if($action==='seats'){
  $room=owned('rooms',intv($post['room_id']??0));if(rows('SELECT a.id FROM seating_assignments a JOIN room_seats q ON q.id=a.seat_id WHERE a.institution_id=? AND q.room_id=?',[inst(),$room['id']]))throw new RuntimeException('لا يمكن تعديل مقاعد قاعة مرتبطة بخريطة.');
  foreach(rows('SELECT * FROM room_seats WHERE room_id=? AND institution_id=?',[$room['id'],inst()]) as $s){$state=enumv($post['seat_state'][$s['id']]??'',['active','aisle','disabled']);run('UPDATE room_seats SET state=?,`accessible`=? WHERE id=? AND institution_id=?',[$state,isset($post['accessible'][$s['id']])?1:0,$s['id'],inst()]);}
  audit('تعديل خريطة مقاعد',(string)$room['id']);flash('حُفظت الممرات والمقاعد المعطلة ومقاعد الوصول. السعة الفعلية لا تتجاوز الأقل من المقاعد النشطة والسعة المسموحة.');return ['room',['id'=>$room['id']]];
 }
 if($action==='import-students'){$count=import_students_file($_FILES['students_file']??[]);audit('استيراد طلبة',(string)$count);flash('تم استيراد '.$count.' طالبًا دون تخطي أي صف.');return ['students',[]];}
 if($action==='token'){
  $kind=enumv($post['kind']??'',['student','invigilator']);$table=$kind==='student'?'students':'invigilators';$person=owned($table,intv($post['id']??0));$token=bin2hex(random_bytes(24));run("UPDATE $table SET portal_hash=? WHERE id=? AND institution_id=?",[hash('sha256',$token),$person['id'],inst()]);audit('إصدار رمز بوابة',$kind.' / '.$person['id']);flash('رمز '.$person['name'].' — انسخه الآن وسلّمه لصاحبه؛ الرمز السابق ألغي: '.$token);return [$kind==='student'?'students':'invigilators',[]];
 }
 if($action==='availability'){
  $id=intv($post['invigilator_id']??0);owned('invigilators',$id);$start=dt($post['starts_at']??'');$end=dt($post['ends_at']??'');if($end<=$start)throw new RuntimeException('نهاية الاستثناء بعد بدايته.');
  if(rows('SELECT a.id FROM invigilation_assignments a JOIN exam_periods p ON p.id=a.period_id WHERE a.institution_id=? AND a.invigilator_id=? AND p.starts_at<? AND p.ends_at>?',[inst(),$id,$end,$start]))throw new RuntimeException('الاستثناء يتعارض مع تكليف قائم؛ استبدل المراقب أولًا.');
  run('INSERT INTO invigilator_availability(institution_id,invigilator_id,starts_at,ends_at,reason) VALUES(?,?,?,?,?)',[inst(),$id,$start,$end,txt($post['reason']??'')]);audit('إضافة استثناء مراقب',(string)$id);flash('سُجل الاستثناء أو الالتزام الرسمي.');return ['invigilators',[]];
 }
 if($action==='period'){
  $id=(int)($post['id']??0);$old=$id?period($id,true):null;if($old){ensure_no_maps($old);if(candidates($old))throw new RuntimeException('أزل المرشحين قبل تعديل زمن الفترة.');}
  $start=dt($post['starts_at']??'');$end=dt($post['ends_at']??'');if($end<=$start||(strtotime($end)-strtotime($start))>24*3600)throw new RuntimeException('الفترة من دقيقة إلى 24 ساعة، ونهايتها بعد بدايتها.');
  $v=['name'=>txt($post['name']??''),'starts_at'=>$start,'ends_at'=>$end,'exam_round'=>txt($post['exam_round']??'',40),'term_name'=>txt($post['term_name']??'',60,false),'study_system'=>enumv($post['study_system']??'',['فصلي','سنوي','بولونيا']),'adjacency'=>enumv($post['adjacency']??'',['none','horizontal','orthogonal']),'grouping'=>enumv($post['grouping']??'',['subject','department']),'strict_separation'=>isset($post['strict_separation'])?1:0];
  if($id)run('UPDATE exam_periods SET '.implode(',',array_map(fn($k)=>'`'.$k.'`=?',array_keys($v))).' WHERE id=? AND institution_id=?',[...array_values($v),$id,inst()]);else{run('INSERT INTO exam_periods(institution_id,year_id,`'.implode('`,`',array_keys($v)).'`) VALUES('.implode(',',array_fill(0,count($v)+2,'?')).')',[inst(),year_id(),...array_values($v)]);$id=(int)db()->lastInsertId();}
  run('DELETE FROM period_rooms WHERE period_id=? AND institution_id=?',[$id,inst()]);foreach(array_unique($post['room_ids']??[]) as $room){owned('rooms',intv($room));run('INSERT INTO period_rooms(institution_id,period_id,room_id) VALUES(?,?,?)',[inst(),$id,$room]);}audit('حفظ فترة امتحانية',(string)$id);flash('حُفظ الجدول وسياسة الفصل والقاعات المختارة.');return ['exam',['id'=>$id]];
 }
 if(in_array($action,['enroll','remove-candidate','generate','monitors','move','replace-monitor','clear','approve','reopen','restore-map'],true)){
  if(in_array($action,['approve','reopen'],true))permit('admin');$p=period(intv($post['period_id']??0),$action!=='reopen');
  if($action==='enroll'){
   ensure_no_maps($p);$subject=owned('subjects',intv($post['subject_id']??0));$count=0;
   if(!empty($post['student_id'])){add_candidate($p,intv($post['student_id']),$subject['id'],!empty($post['allow_carry'])?txt($post['carry_note']??''):'');$count=1;}
   else{$shift=($post['shift']??'')===''?'':enumv($post['shift'],['صباحي','مسائي']);$section=txt($post['section_name']??'',80,false);$q='SELECT id FROM students WHERE institution_id=? AND year_id=? AND stage_id=? AND department_id=? AND active=1';$params=[inst(),$p['year_id'],$subject['stage_id'],$subject['department_id']];if($shift){$q.=' AND shift=?';$params[]=$shift;}if($section){$q.=' AND section_name=?';$params[]=$section;}foreach(rows($q.' ORDER BY id',$params) as $s){add_candidate($p,(int)$s['id'],(int)$subject['id']);$count++;}}
   if(!$count)throw new RuntimeException('لا توجد أسماء مؤهلة لهذا الاختيار.');audit('ترشيح طلبة',$p['id'].' / '.$count);flash('رُشح '.$count.' طالبًا.');
  }
  if($action==='remove-candidate'){ensure_no_maps($p);run('DELETE FROM exam_candidates WHERE institution_id=? AND period_id=? AND student_id=?',[inst(),$p['id'],intv($post['student_id']??0)]);audit('إزالة ترشيح',(string)$p['id']);flash('أزيل الترشيح.');}
  if($action==='generate'){generate_students($p);flash('وُزع الطلبة دون تكرار أو تجاوز السعة. أعد توليد المراقبين قبل الاعتماد.');}
  if($action==='monitors'){generate_monitors($p);flash('وُزع المراقبون وفق التوفر والعبء بالدقائق.');}
  if($action==='clear'){version($p,'حفظ قبل إفراغ الخريطة');run('DELETE FROM invigilation_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);run('DELETE FROM seating_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);version($p,'إفراغ مسودة');flash('أُفرغت المسودة، وبقيت نسختها السابقة في السجل.');}
  if($action==='move'){
   $student=intv($post['student_id']??0);$seat=owned('room_seats',intv($post['seat_id']??0));$a=rows('SELECT id FROM seating_assignments WHERE institution_id=? AND period_id=? AND student_id=?',[inst(),$p['id'],$student])[0]??null;if(!$a)throw new RuntimeException('الطالب غير موزع في الفترة.');run('UPDATE seating_assignments SET seat_id=? WHERE id=? AND institution_id=?',[$seat['id'],$a['id'],inst()]);$issues=map_issues($p,false);if($issues['errors'])throw new RuntimeException(implode(' / ',$issues['errors']));run('DELETE FROM invigilation_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);version($p,'نقل طالب يدويًا');flash('تم النقل بعد فحص القيود؛ أعد توزيع المراقبين لأن القاعات المشغولة قد تتغير.');
  }
  if($action==='replace-monitor'){
   $old=rows('SELECT * FROM invigilation_assignments WHERE id=? AND institution_id=? AND period_id=?',[intv($post['assignment_id']??0),inst(),$p['id']])[0]??null;if(!$old)throw new RuntimeException('التكليف غير موجود.');$new=owned('invigilators',intv($post['invigilator_id']??0));if(!monitor_available($p,(int)$new['id'])||($old['role']==='chief'&&$new['duty']==='observer'))throw new RuntimeException('البديل غير متاح أو غير مؤهل.');run('UPDATE invigilation_assignments SET invigilator_id=? WHERE id=? AND institution_id=?',[$new['id'],$old['id'],inst()]);$issues=map_issues($p);if($issues['errors'])throw new RuntimeException(implode(' / ',$issues['errors']));version($p,'استبدال مراقب #'.$old['invigilator_id'].' بـ #'.$new['id']);flash('حُفظ البديل وسُجل تغيير التكليف.');
  }
  if($action==='approve'){
   $issues=map_issues($p);if($issues['errors'])throw new RuntimeException(implode(' / ',$issues['errors']));run("UPDATE exam_periods SET status='approved' WHERE id=? AND institution_id=?",[$p['id'],inst()]);version($p,'اعتماد وقفل الخريطة');$fresh=period((int)$p['id']);$fresh['approved_snapshot']=null;$s=snapshot($fresh);run('UPDATE exam_periods SET approved_snapshot=? WHERE id=? AND institution_id=?',[json_encode($s,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR),$p['id'],inst()]);flash('اعتُمدت الخريطة وقُفلت، وأصبحت النتائج متاحة في بوابات الاستعلام.');
  }
  if($action==='reopen'){if($p['status']!=='approved')throw new RuntimeException('الفترة مسودة بالفعل.');if(empty($post['reason']))throw new RuntimeException('سبب فتح الاعتماد مطلوب.');version($p,'حفظ الاعتماد قبل إعادة الفتح');run("UPDATE exam_periods SET status='draft',approved_snapshot=NULL WHERE id=? AND institution_id=?",[$p['id'],inst()]);version($p,'فتح للمراجعة: '.txt($post['reason']));flash('فُتحت المسودة وسُحب ظهورها من البوابات إلى إعادة اعتمادها.');}
  if($action==='restore-map'){
   $v=owned('map_versions',intv($post['version_id']??0));if((int)$v['period_id']!==(int)$p['id'])throw new RuntimeException('النسخة لفترة أخرى.');$s=json_decode($v['snapshot'],true,512,JSON_THROW_ON_ERROR);run('DELETE FROM invigilation_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);run('DELETE FROM seating_assignments WHERE institution_id=? AND period_id=?',[inst(),$p['id']]);
   foreach($s['students'] as $a){owned('students',(int)$a['student_id']);owned('room_seats',(int)$a['seat_id']);run('INSERT INTO seating_assignments(institution_id,period_id,student_id,seat_id) VALUES(?,?,?,?)',[inst(),$p['id'],$a['student_id'],$a['seat_id']]);}
   foreach($s['monitors'] as $a){owned('rooms',(int)$a['room_id']);owned('invigilators',(int)$a['invigilator_id']);run('INSERT INTO invigilation_assignments(institution_id,period_id,room_id,invigilator_id,role) VALUES(?,?,?,?,?)',[inst(),$p['id'],$a['room_id'],$a['invigilator_id'],$a['role']]);}
   $issues=map_issues($p,!empty($s['monitors']));if($issues['errors'])throw new RuntimeException('النسخة لا تطابق المدخلات الحالية: '.implode(' / ',$issues['errors']));version($p,'استعادة نسخة '.$v['revision']);flash('استُعيد التوزيع كمسودة بعد فحص البيانات الحالية.');
  }return ['exam',['id'=>$p['id']]];
 }
 if($action==='settings'){permit('admin');run('UPDATE institutions SET name=?,university=? WHERE id=?',[txt($post['name']??''),txt($post['university']??'',180,false),inst()]);audit('إعدادات المؤسسة','تحديث الاسم');flash('حُفظت الإعدادات.');return ['settings',[]];}
 if($action==='user'){
  permit('admin');$id=(int)($post['id']??0);$role=enumv($post['role']??'',['admin','planner','viewer']);$username=txt($post['username']??'',80);if(!preg_match('/^[A-Za-z0-9_.-]{3,80}$/',$username))throw new RuntimeException('اسم المستخدم 3–80 حرفًا لاتينيًا أو رقمًا.');$password=$post['password']??'';
  if($id){$old=owned('users',$id);if($old['role']==='admin'&&$role!=='admin'&&(int)rows("SELECT COUNT(*) AS n FROM users WHERE institution_id=? AND role='admin'",[inst()])[0]['n']<=1)throw new RuntimeException('لا يمكن إزالة آخر مدير.');run('UPDATE users SET username=?,role=? WHERE id=? AND institution_id=?',[$username,$role,$id,inst()]);if($password!==''){if(strlen($password)<12)throw new RuntimeException('كلمة المرور 12 حرفًا على الأقل.');run('UPDATE users SET password_hash=? WHERE id=? AND institution_id=?',[password_hash($password,PASSWORD_DEFAULT),$id,inst()]);}}
  else{if(strlen($password)<12)throw new RuntimeException('كلمة المرور 12 حرفًا على الأقل.');run('INSERT INTO users(institution_id,username,password_hash,role) VALUES(?,?,?,?)',[inst(),$username,password_hash($password,PASSWORD_DEFAULT),$role]);}
  audit('حفظ مستخدم',$username.' / '.$role);flash('حُفظ الحساب والصلاحيات.');return ['settings',[]];
 }
 if($action==='password'){$u=me();if(!password_verify($post['old_password']??'',$u['password_hash'])||strlen($post['new_password']??'')<12)throw new RuntimeException('تحقق من الحالية والجديدة 12 حرفًا على الأقل.');run('UPDATE users SET password_hash=? WHERE id=? AND institution_id=?',[password_hash($post['new_password'],PASSWORD_DEFAULT),$u['id'],inst()]);session_regenerate_id(true);audit('تغيير كلمة مرور','الحساب الحالي');flash('تم تغيير كلمة المرور.');return ['settings',[]];}
 if($action==='new-institution'){
  permit('admin');$name=txt($post['name']??'');$username=txt($post['username']??'',80);$password=$post['password']??'';if(!preg_match('/^[A-Za-z0-9_.-]{3,80}$/',$username)||strlen($password)<12)throw new RuntimeException('حساب المؤسسة الجديدة يحتاج اسمًا صالحًا وكلمة مرور 12 حرفًا.');run('INSERT INTO institutions(name,university) VALUES(?,?)',[$name,txt($post['university']??'',180,false)]);$id=(int)db()->lastInsertId();run('INSERT INTO users(institution_id,username,password_hash,role) VALUES(?,?,?,?)',[$id,$username,password_hash($password,PASSWORD_DEFAULT),'admin']);run('INSERT INTO academic_years(institution_id,name) VALUES(?,?)',[$id,txt($post['year_name']??'',60)]);audit('إنشاء مؤسسة مستقلة',$name);flash('أُنشئت المؤسسة. سجل خروجك وادخل بحسابها لإدارتها.');return ['settings',[]];
 }
 if($action==='restore-backup'){permit('admin');if(empty($post['confirmed']))throw new RuntimeException('تأكيد الاستبدال مطلوب.');$file=$_FILES['backup_file']??[];if(($file['error']??1)!==UPLOAD_ERR_OK||($file['size']??0)>20*1024*1024)throw new RuntimeException('ملف نسخة موقعة حتى 20 ميغابايت مطلوب.');restore_backup($file);run('UPDATE students SET portal_hash=NULL WHERE institution_id=?',[inst()]);run('UPDATE invigilators SET portal_hash=NULL WHERE institution_id=?',[inst()]);flash('استُعيدت بيانات المؤسسة. أُلغيت رموز البوابات وتحتاج إصدارًا جديدًا. بقيت الحسابات وسجل التدقيق.');return ['settings',[]];}
 throw new RuntimeException('الإجراء غير معروف.');
}
