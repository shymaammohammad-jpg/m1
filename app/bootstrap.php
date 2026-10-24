<?php
declare(strict_types=1);
header('X-Content-Type-Options: nosniff');header('X-Frame-Options: DENY');header('Cache-Control: no-store');
header("Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; base-uri 'self'; frame-ancestors 'none'");
date_default_timezone_set('Asia/Baghdad');ini_set('session.use_strict_mode','1');
session_set_cookie_params(['httponly'=>true,'secure'=>!empty($_SERVER['HTTPS'])&&$_SERVER['HTTPS']!=='off','samesite'=>'Strict']);session_start();$_SESSION['csrf']??=bin2hex(random_bytes(32));
if(is_file(dirname(__DIR__).'/vendor/autoload.php'))require dirname(__DIR__).'/vendor/autoload.php';
require __DIR__.'/solver.php';
function h(mixed $v):string{return htmlspecialchars((string)$v,ENT_QUOTES,'UTF-8');}
function csrf():string{return '<input type="hidden" name="csrf" value="'.h($_SESSION['csrf']).'">';}
function db():PDO {static $p; if($p)return $p;$f=dirname(__DIR__).'/config.php';if(!is_file($f))throw new RuntimeException('انسخ config.example.php إلى config.php واضبط قاعدة MySQL.');$c=require $f;$p=new PDO($c['dsn'],$c['user'],$c['password'],[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC,PDO::ATTR_EMULATE_PREPARES=>false]);$p->exec("SET time_zone='+03:00'");return $p;}
function rows(string $q,array $a=[]):array{$s=db()->prepare($q);$s->execute($a);return $s->fetchAll();}
function run(string $q,array $a=[]):void{db()->prepare($q)->execute($a);}
function inst():int{return (int)($_SESSION['institution_id']??0);}
function me():array {return rows('SELECT * FROM users WHERE id=? AND institution_id=?',[(int)($_SESSION['uid']??0),inst()])[0]??[];}
function can(string $ability):bool{$role=me()['role']??'';return $role==='admin'||($ability==='write'&&$role==='planner');}
function permit(string $ability='write'):void{if(!can($ability))throw new RuntimeException('حسابك لا يملك صلاحية هذا الإجراء.');}
function owned(string $table,int $id):array {
 if(!in_array($table,['academic_years','departments','stages','subjects','students','rooms','room_seats','exam_periods','invigilators','invigilator_availability','users','map_versions'],true))throw new RuntimeException('نوع سجل غير معروف.');
 $r=rows("SELECT * FROM $table WHERE id=? AND institution_id=?",[$id,inst()])[0]??null;if(!$r)throw new RuntimeException('السجل غير موجود ضمن مؤسستك.');return $r;
}
function audit(string $a,string $detail):void{run('INSERT INTO audit_logs(institution_id,user_id,action,details) VALUES(?,?,?,?)',[inst(),$_SESSION['uid'],$a,$detail]);}
function begin_write():void{db()->beginTransaction();rows('SELECT id FROM institutions WHERE id=? FOR UPDATE',[inst()]);}
function flash(string $s):void{$_SESSION['flash']=$s;}
function go(string $page='dashboard',array $params=[]):never{header('Location: index.php?'.http_build_query(['page'=>$page]+$params));exit;}
function intv(mixed $v,int $min=1,int $max=2147483647):int{$n=filter_var($v,FILTER_VALIDATE_INT);if($n===false||$n<$min||$n>$max)throw new InvalidArgumentException('قيمة عددية خارج النطاق المسموح.');return $n;}
function txt(mixed $v,int $max=180,bool $required=true):string{$s=trim((string)$v);if(($required&&$s==='')||!preg_match('//u',$s)||mb_strlen($s,'UTF-8')>$max)throw new InvalidArgumentException('أكمل الحقول النصية ضمن الطول المسموح.');return $s;}
function dt(string $s):string{$d=DateTimeImmutable::createFromFormat('!Y-m-d\TH:i',$s);if(!$d||$d->format('Y-m-d\TH:i')!==$s)throw new InvalidArgumentException('التاريخ والوقت غير صحيحين.');return $d->format('Y-m-d H:i:s');}
function dt_input(?string $s):string{return $s?substr(str_replace(' ','T',$s),0,16):'';}
function enumv(mixed $v,array $allowed):string{if(!in_array($v,$allowed,true))throw new InvalidArgumentException('اختيار غير صحيح.');return $v;}
function year_id():int{$years=rows('SELECT id FROM academic_years WHERE institution_id=? ORDER BY id DESC',[inst()]);$ids=array_column($years,'id');if(!in_array($_SESSION['year_id']??0,$ids))$_SESSION['year_id']=$ids[0]??0;return (int)$_SESSION['year_id'];}
function field(string $label,string $name,mixed $value='',string $type='text',string $attrs='',bool $required=true):void{echo '<label>'.h($label).'<input type="'.h($type).'" name="'.h($name).'" value="'.h($value).'" '.($required?'required ':'').$attrs.'></label>';}
function selectf(string $label,string $name,array $options,mixed $value='',bool $required=true):void{echo '<label>'.h($label).'<select name="'.h($name).'" '.($required?'required':'').'><option value="">اختر…</option>';foreach($options as $key=>$text)echo '<option value="'.h($key).'" '.((string)$key===(string)$value?'selected':'').'>'.h($text).'</option>';echo '</select></label>';}
function opts(string $table,string $name='name',string $extra='',array $params=[]):array{$out=[];foreach(rows("SELECT id,$name FROM $table WHERE institution_id=? $extra ORDER BY $name",[inst(),...$params]) as $r)$out[$r['id']]=$r[$name];return $out;}
function secret_key():string{$f=dirname(__DIR__).'/storage/backup.key';if(!is_file($f)){if(!is_dir(dirname($f)))mkdir(dirname($f),0700,true);$key=bin2hex(random_bytes(32));$handle=@fopen($f,'x');if($handle){fwrite($handle,$key);fclose($handle);chmod($f,0600);}}$key=@file_get_contents($f);if(!$key)throw new RuntimeException('تعذّر قراءة مفتاح النسخ الاحتياطي في storage.');return trim($key);}
require __DIR__.'/services.php';require __DIR__.'/reports.php';
