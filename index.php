<?php
require __DIR__.'/app/bootstrap.php';require __DIR__.'/app/actions.php';
$page=$_GET['page']??'dashboard';$error='';$installed=false;$connected=false;$portalResult=null;
try{db();$connected=true;$installed=(int)db()->query('SELECT COUNT(*) FROM users')->fetchColumn()>0;}catch(Throwable $e){$error='أنشئ قاعدة maqad في phpMyAdmin، وانسخ config.example.php إلى config.php واضبط الاتصال.';}
if(!$installed)$page='install';elseif(!empty($_SESSION['uid'])&&!me()){$_SESSION=[];$page='login';}elseif(empty($_SESSION['uid'])&&$page!=='portal')$page='login';
try{
 if($_SERVER['REQUEST_METHOD']==='POST'){
  if(!hash_equals($_SESSION['csrf']??'',(string)($_POST['csrf']??'')))throw new RuntimeException('انتهت صلاحية النموذج؛ أعد تحميل الصفحة.');$action=$_POST['action']??'';
  if($action==='install'&&!$installed&&$connected){
   if(!in_array($_SERVER['REMOTE_ADDR']??'',['127.0.0.1','::1'],true))throw new RuntimeException('نفّذ التثبيت أول مرة من الحاسبة المحلية.');
   $username=txt($_POST['username']??'',80);$password=$_POST['password']??'';if(!preg_match('/^[A-Za-z0-9_.-]{3,80}$/',$username)||strlen($password)<12)throw new RuntimeException('اسم المستخدم لاتيني 3–80 حرفًا، وكلمة المرور 12 حرفًا على الأقل.');
   if((int)(rows("SELECT GET_LOCK('maqad-install',10) AS acquired")[0]['acquired']??0)!==1)throw new RuntimeException('الإعداد قيد التنفيذ، أعد المحاولة لاحقًا.');foreach(explode(';',file_get_contents(__DIR__.'/database/schema.sql')) as $sql)if(trim($sql))db()->exec($sql);
   db()->beginTransaction();if((int)db()->query('SELECT COUNT(*) FROM users')->fetchColumn()>0)throw new RuntimeException('التثبيت مكتمل بالفعل.');
   run('INSERT INTO institutions(name,university) VALUES(?,?)',[txt($_POST['institution']??''),txt($_POST['university']??'',180,false)]);$id=(int)db()->lastInsertId();run('INSERT INTO users(institution_id,username,password_hash,role) VALUES(?,?,?,?)',[$id,$username,password_hash($password,PASSWORD_DEFAULT),'admin']);run('INSERT INTO academic_years(institution_id,name) VALUES(?,?)',[$id,txt($_POST['year_name']??'',60)]);secret_key();db()->commit();rows("SELECT RELEASE_LOCK('maqad-install')");flash('اكتمل إعداد نظام مقعد. سجل الدخول بحساب المدير.');go('login');
  }elseif($action==='login'&&$installed){
   if(time()<($_SESSION['login_after']??0))throw new RuntimeException('انتظر قليلًا قبل إعادة المحاولة.');$u=rows('SELECT * FROM users WHERE username=?',[trim($_POST['username']??'')])[0]??null;
   if(!$u||!password_verify($_POST['password']??'',$u['password_hash'])){$_SESSION['login_after']=time()+3;throw new RuntimeException('اسم المستخدم أو كلمة المرور غير صحيحة.');}session_regenerate_id(true);$_SESSION['uid']=$u['id'];$_SESSION['institution_id']=$u['institution_id'];$_SESSION['csrf']=bin2hex(random_bytes(32));unset($_SESSION['year_id']);go();
  }elseif($action==='logout'){$_SESSION=[];session_destroy();go('login');}
  elseif($action==='portal'&&$installed){
   if(time()<($_SESSION['portal_after']??0))throw new RuntimeException('انتظر قليلًا ثم أعد المحاولة.');$kind=enumv($_POST['portal_kind']??'',['student','invigilator']);$table=$kind==='student'?'students':'invigilators';$code=trim($_POST['lookup_code']??'');$person=strlen($code)===48?rows("SELECT * FROM $table WHERE portal_hash=? AND active=1",[hash('sha256',$code)])[0]??null:null;
   if(!$person){$_SESSION['portal_after']=time()+3;throw new RuntimeException('رمز الاستعلام غير صالح أو ألغي.');}$portalResult=['kind'=>$kind,'person'=>$person,'items'=>[]];
   foreach(rows("SELECT * FROM exam_periods WHERE institution_id=? AND status='approved' AND approved_snapshot IS NOT NULL ORDER BY starts_at",[$person['institution_id']]) as $p){$s=json_decode($p['approved_snapshot'],true);foreach($s[$kind==='student'?'students':'monitors'] as $item)if((int)$item[$kind==='student'?'student_id':'invigilator_id']===(int)$person['id'])$portalResult['items'][]=['period'=>$p,'item'=>$item];}
  }elseif(!empty($_SESSION['uid'])){
   if($action==='year'){owned('academic_years',intv($_POST['year_id']??0));$_SESSION['year_id']=(int)$_POST['year_id'];go();}
   if($action!=='password')permit('write');begin_write();[$target,$params]=handle_action($action,$_POST);db()->commit();go($target,$params);
  }else throw new RuntimeException('سجل الدخول أولًا.');
 }
 if($installed&&!empty($_SESSION['uid'])&&$page!=='portal'){
  if(isset($_GET['download'])){
   $download=$_GET['download'];
   if($download==='template'){sheet_download([['code','name','department','stage','shift','section','needs_access']],'maqad-students-template');}
   if($download==='students'){$data=[['code','name','department','stage','shift','section','needs_access']];foreach(rows('SELECT s.*,d.name AS department,t.name AS stage FROM students s JOIN departments d ON d.id=s.department_id JOIN stages t ON t.id=s.stage_id WHERE s.institution_id=? AND s.year_id=? ORDER BY s.code',[inst(),year_id()]) as $s)$data[]=[$s['code'],$s['name'],$s['department'],$s['stage'],$s['shift'],$s['section_name'],$s['needs_access']];sheet_download($data,'maqad-students');}
   if($download==='backup'){permit('admin');begin_write();$backup=export_backup();audit('تنزيل نسخة احتياطية','بيانات المؤسسة الموقعة');db()->commit();header('Content-Type: application/json; charset=utf-8');header('Content-Disposition: attachment; filename="maqad-backup-'.date('Ymd-His').'.json"');echo json_encode($backup,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);exit;}
  }
  if($page==='reports'&&in_array($_GET['format']??'',['pdf','xlsx'],true)){$p=period(intv($_GET['period_id']??0));$type=enumv($_GET['type']??'map',array_keys(REPORT_TYPES));$room=(int)($_GET['room_id']??0);$student=(int)($_GET['student_id']??0);$data=report_data($p);if($_GET['format']==='pdf')pdf_download($data,$type,$room,$student,enumv($_GET['paper']??'A4',['A4','A3']));sheet_download(report_rows($data,$type,$room,$student),'maqad-'.$type);}
 }
}catch(Throwable $e){if($connected&&db()->inTransaction())db()->rollBack();$error=$e instanceof PDOException?'تعذر الحفظ: يوجد سجل مكرر أو ارتباط يمنع الحذف. لم تُحفظ تغييرات جزئية.':$e->getMessage();}
$public=in_array($page,['install','login','portal'],true);$nav=['dashboard'=>'لوحة التحكم','structure'=>'الأقسام والمراحل','rooms'=>'القاعات والمقاعد','students'=>'الطلبة','lookup'=>'أماكن الجلوس','periods'=>'الجدول الامتحاني','maps'=>'الخرائط الامتحانية','invigilators'=>'المراقبون','reports'=>'التقارير والطباعة','settings'=>'الإعدادات والصلاحيات','audit'=>'سجل العمليات'];
$institution=(!$public&&inst())?rows('SELECT * FROM institutions WHERE id=?',[inst()])[0]:['name'=>'نظام مقعد'];
?>
<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#087c55"><title>نظام مقعد — الخرائط الامتحانية</title><link rel="stylesheet" href="assets/style.css"><script src="assets/app.js" defer></script></head><body class="<?=$public?'public':''?>">
<?php if(!$public):?><aside class="sidebar"><a class="brand" href="index.php"><span class="brand-icon">م</span><span>مقعد<small>نظام الخرائط الامتحانية</small></span></a><div class="institution"><?=h($institution['name'])?></div><nav><?php foreach($nav as $key=>$label):?><a href="?page=<?=h($key)?>" class="<?=($page===$key||($page==='exam'&&$key==='maps')||($page==='room'&&$key==='rooms'))?'active':''?>"><span class="nav-dot"></span><?=h($label)?></a><?php endforeach;?></nav><a class="portal-link" href="?page=portal">بوابة الطالب والمراقب ↗</a><div class="side-footer">تخطيط منظم · مقاعد واضحة</div></aside>
<div class="workspace"><header class="topbar"><div><strong><?=h($institution['name'])?></strong><span class="muted"> / <?=h($nav[$page]??($page==='exam'?'تفاصيل الخريطة':'محرر القاعة'))?></span></div><div class="top-actions"><form method="post" class="year-form"><?=csrf()?><input type="hidden" name="action" value="year"><select name="year_id" aria-label="العام الدراسي"><?php foreach(opts('academic_years') as $id=>$name):?><option value="<?=$id?>" <?=year_id()===$id?'selected':''?>><?=h($name)?></option><?php endforeach;?></select><button class="ghost">تبديل العام</button></form><span class="user-chip"><?=h(me()['username'])?></span><form method="post"><?=csrf()?><input type="hidden" name="action" value="logout"><button class="ghost">خروج</button></form></div></header>
<?php else:?><header class="public-header"><a class="brand" href="index.php"><span class="brand-icon">م</span><span>مقعد<small>نظام الخرائط الامتحانية</small></span></a><a href="?page=<?=$page==='portal'?'login':'portal'?>"><?=$page==='portal'?'دخول الإدارة':'بوابة الطالب والمراقب'?></a></header><?php endif;?>
<main><?php if($error):?><div role="alert" class="alert error"><?=h($error)?></div><?php endif;?><?php if(isset($_SESSION['flash'])):?><div role="status" class="alert success"><?=h($_SESSION['flash'])?></div><?php unset($_SESSION['flash']);endif;?>
<?php
try{
 if($public)require __DIR__.'/app/public_views.php';
 elseif($page==='dashboard')require __DIR__.'/app/dashboard.php';
 elseif($page==='lookup')require __DIR__.'/app/lookup.php';
 elseif($page==='structure')require __DIR__.'/app/structure.php';
 elseif(in_array($page,['students','invigilators'],true))require __DIR__.'/app/people.php';
 elseif(in_array($page,['rooms','room'],true))require __DIR__.'/app/rooms.php';
 elseif(in_array($page,['periods','maps','exam'],true))require __DIR__.'/app/exams.php';
 elseif($page==='reports')require __DIR__.'/app/report_view.php';
 elseif(in_array($page,['settings','audit'],true))require __DIR__.'/app/settings.php';
 else {http_response_code(404);echo '<section class="card"><h1>الصفحة غير موجودة</h1></section>';}
}catch(Throwable $e){echo '<div role="alert" class="alert error">'.h($e instanceof PDOException?'تعذر قراءة البيانات. تحقق من اكتمال التثبيت.':$e->getMessage()).'</div>';}
?>
</main><footer>نظام مقعد · إدارة القاعات والخرائط الامتحانية · <?=date('Y')?></footer><?php if(!$public):?></div><?php endif;?></body></html>
