<?php
declare(strict_types=1);
function overlaps(string $aStart,string $aEnd,string $bStart,string $bEnd):bool{return $aStart<$bEnd && $aEnd>$bStart;}
function seat_neighbors(array $a,array $b,string $mode):bool {
 if($a['room_id']!==$b['room_id']||$mode==='none')return false;
 $dr=abs((int)$a['row_no']-(int)$b['row_no']);$dc=abs((int)$a['col_no']-(int)$b['col_no']);
 return $mode==='horizontal'?($dr===0&&$dc===1):($dr+$dc===1);
}
final class SeatingSolver {
 private int $nodes=0;private float $deadline;private array $neighbors=[];private array $seats=[];private bool $strict;private string $mode;
 public function solve(array $students,array $rooms,array $seats,string $mode='horizontal',bool $strict=false):array {
  if(!$students)throw new RuntimeException('لا توجد قائمة طلبة مؤهلين للتوزيع.');
  if(!in_array($mode,['none','horizontal','orthogonal'],true))throw new RuntimeException('سياسة فصل غير صحيحة.');
  if(count(array_unique(array_column($students,'id')))!==count($students))throw new RuntimeException('طالب مكرر في المدخلات.');
  $this->nodes=0;$this->deadline=microtime(true)+5;$this->strict=$strict;$this->mode=$mode;
  usort($rooms,fn($a,$b)=>(($a['status']==='reserve')<=>($b['status']==='reserve'))?:((int)$b['capacity']<=>(int)$a['capacity'])?:((int)$a['id']<=>(int)$b['id']));
  $selected=[];$lastReason='السعة المتاحة أو المقاعد الملائمة للاحتياجات الخاصة لا تكفي.';
  foreach($rooms as $room){
   if(!in_array($room['status'],['available','reserve'],true))continue;
   $selected[]=$room;$roomIds=array_column($selected,'id');$available=array_values(array_filter($seats,fn($s)=>in_array($s['room_id'],$roomIds)&&$s['state']==='active'));
   $capacity=0;foreach($selected as $r)$capacity+=min((int)$r['capacity'],count(array_filter($available,fn($s)=>$s['room_id']===$r['id'])));
   if($capacity<count($students))continue;
   if(count(array_filter($available,fn($s)=>(bool)$s['accessible']))<count(array_filter($students,fn($s)=>(bool)$s['needs_access'])))continue;
   usort($available,fn($a,$b)=>(array_search($a['room_id'],$roomIds)<=>array_search($b['room_id'],$roomIds))?:($a['row_no']<=>$b['row_no'])?:($a['col_no']<=>$b['col_no']));
   $this->seats=[];foreach($available as $s)$this->seats[$s['id']]=$s;
   $positions=[];foreach($available as $s)$positions[$s['room_id'].':'.$s['row_no'].':'.$s['col_no']]=$s['id'];
   $this->neighbors=[];
   foreach($available as $s){$neighbors=[];$directions=$mode==='none'?[]:($mode==='horizontal'?[[0,-1],[0,1]]:[[0,-1],[0,1],[-1,0],[1,0]]);foreach($directions as [$dr,$dc]){$key=$s['room_id'].':'.($s['row_no']+$dr).':'.($s['col_no']+$dc);if(isset($positions[$key]))$neighbors[]=$positions[$key];}$this->neighbors[$s['id']]=$neighbors;}
   $limits=[];foreach($selected as $r)$limits[$r['id']]=(int)$r['capacity'];
   $buckets=[];usort($students,fn($a,$b)=>(int)$a['id']<=>(int)$b['id']);
   foreach($students as $s)$buckets[$s['group'].':'.(int)$s['needs_access']][]=$s;
   ksort($buckets,SORT_STRING);
   $result=$this->search($buckets,[],[],[],$limits);
   if($result!==null){$out=[];foreach($result as $seatId=>$student)$out[]=['student_id'=>$student['id'],'seat_id'=>$seatId];usort($out,fn($a,$b)=>$a['student_id']<=>$b['student_id']);return $out;}
   $lastReason='لا يوجد توزيع يحقق الفصل الإلزامي ضمن القاعات والمقاعد المحددة.';
  }
  throw new RuntimeException($lastReason.' لم يُحفظ توزيع جزئي.');
 }
 private function search(array $buckets,array $placed,array $used,array $loads,array $limits):?array {
  if(!$buckets)return $placed;
  if(++$this->nodes>80000||microtime(true)>$this->deadline)throw new RuntimeException('انتهى حد البحث دون حسم قابلية التوزيع. وسّع القاعات أو اجعل الفصل تفضيليًا؛ لم يُحفظ توزيع جزئي.');
  $chosen=null;$chosenDomain=[];$best=PHP_INT_MAX;$largest=-1;
  foreach($buckets as $key=>$list){$s=$list[0];$domain=[];foreach($this->seats as $id=>$seat){if(isset($used[$id])||($loads[$seat['room_id']]??0)>=$limits[$seat['room_id']]||($s['needs_access']&&!$seat['accessible']))continue;
    $conflicts=0;foreach($this->neighbors[$id] as $near)if(isset($placed[$near])&&$placed[$near]['group']===$s['group'])$conflicts++;
    if($this->strict&&$conflicts)continue;
    $domain[]=['id'=>$id,'score'=>$conflicts,'access_penalty'=>!$s['needs_access']&&$seat['accessible']?1:0];
   }
   if(!$domain||($this->strict&&count($domain)<count($list)))return null;
   $rank=$s['needs_access']?-1:count($domain);
   if($chosen===null||$rank<$best||($rank===$best&&count($list)>$largest)){$chosen=$key;$chosenDomain=$domain;$best=$rank;$largest=count($list);}
  }
  usort($chosenDomain,fn($a,$b)=>($a['score']<=>$b['score'])?:($a['access_penalty']<=>$b['access_penalty'])?:($a['id']<=>$b['id']));
  $student=array_shift($buckets[$chosen]);if(!$buckets[$chosen])unset($buckets[$chosen]);
  foreach($chosenDomain as $candidate){$seatId=$candidate['id'];$room=$this->seats[$seatId]['room_id'];$next=$placed;$next[$seatId]=$student;$u=$used;$u[$seatId]=true;$l=$loads;$l[$room]=($l[$room]??0)+1;
   $r=$this->search($buckets,$next,$u,$l,$limits);if($r!==null)return $r;if(!$this->strict)return null;
  }return null;
 }
}
function solve_monitors(array $people,array $rooms,int $duration):array {
 $people=array_values(array_filter($people,fn($p)=>(bool)$p['active']));$result=[];$used=[];$load=[];foreach($people as $p)$load[$p['id']]=(int)($p['work_minutes']??0)+(int)($p['baseline_minutes']??0);
 usort($rooms,fn($a,$b)=>$a['id']<=>$b['id']);
 $choose=function(bool $chief)use(&$people,&$used,&$load):array{$eligible=array_values(array_filter($people,fn($p)=>!isset($used[$p['id']])&&(!$chief||$p['duty']!=='observer')));usort($eligible,fn($a,$b)=>($load[$a['id']]<=>$load[$b['id']])?:($a['id']<=>$b['id']));if(!$eligible)throw new RuntimeException('المراقبون المتاحون أو المؤهلون لرئاسة القاعات لا يكفون.');$p=$eligible[0];$used[$p['id']]=true;return $p;};
 foreach($rooms as $room){$p=$choose(true);$load[$p['id']]+=$duration;$result[]=['room_id'=>$room['id'],'invigilator_id'=>$p['id'],'role'=>'chief'];}
 foreach($rooms as $room)for($i=1;$i<(int)$room['required_monitors'];$i++){$p=$choose(false);$load[$p['id']]+=$duration;$result[]=['room_id'=>$room['id'],'invigilator_id'=>$p['id'],'role'=>'observer'];}
 return $result;
}
