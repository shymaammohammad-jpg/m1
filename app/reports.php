<?php
function report_data(array $p):array {if($p['status']==='approved' && $p['approved_snapshot'])return json_decode($p['approved_snapshot'],true,512,JSON_THROW_ON_ERROR);return snapshot($p);}
function csv_cell(mixed $s):string{$s=(string)$s;return preg_match('/^\s*[=+@-]/u',$s)?"'".$s:$s;}
function sheet_download(array $data,string $filename):never {
 if(!class_exists(\PhpOffice\PhpSpreadsheet\Spreadsheet::class))throw new RuntimeException('مكتبة Excel غير مثبتة؛ اتبع دليل التثبيت.');
 $book=new \PhpOffice\PhpSpreadsheet\Spreadsheet();$sheet=$book->getActiveSheet();$sheet->setRightToLeft(true);
 foreach($data as $ri=>$row)foreach(array_values($row) as $ci=>$cell)$sheet->getCell([$ci+1,$ri+1])->setValueExplicit((string)$cell,\PhpOffice\PhpSpreadsheet\Cell\DataType::TYPE_STRING);
 $sheet->getStyle('1:1')->getFont()->setBold(true);$sheet->freezePane('A2');foreach(range(1,count($data[0]??[1])) as $i)$sheet->getColumnDimension(\PhpOffice\PhpSpreadsheet\Cell\Coordinate::stringFromColumnIndex($i))->setWidth(24);
 header('Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');header('Content-Disposition: attachment; filename="'.$filename.'.xlsx"');(new \PhpOffice\PhpSpreadsheet\Writer\Xlsx($book))->save('php://output');exit;
}
function import_students_file(array $file):int {
 if(($file['error']??1)!==UPLOAD_ERR_OK||($file['size']??0)>5*1024*1024)throw new RuntimeException('ملف CSV أو XLSX حتى 5 ميغابايت مطلوب.');
 $ext=strtolower(pathinfo($file['name'],PATHINFO_EXTENSION));$data=[];
 if($ext==='csv'){$f=fopen($file['tmp_name'],'r');while(($r=fgetcsv($f,0,',','"',''))!==false){if(count($data)>5000)throw new RuntimeException('حد الاستيراد 5000 طالب.');$data[]=$r;}fclose($f);}
 elseif($ext==='xlsx'){
  if(!class_exists(\PhpOffice\PhpSpreadsheet\Reader\Xlsx::class))throw new RuntimeException('ثبّت مكتبة Excel أولًا.');
  $z=new ZipArchive();if($z->open($file['tmp_name'])!==true)throw new RuntimeException('ملف XLSX غير صالح.');$size=0;for($i=0;$i<$z->numFiles;$i++)$size+=$z->statIndex($i)['size'];$z->close();if($size>30*1024*1024)throw new RuntimeException('حجم محتويات XLSX يتجاوز 30 ميغابايت.');
  $reader=new \PhpOffice\PhpSpreadsheet\Reader\Xlsx();$reader->setReadDataOnly(true);$infos=$reader->listWorksheetInfo($file['tmp_name']);if(!$infos||$infos[0]['totalRows']>5001||$infos[0]['totalColumns']>7)throw new RuntimeException('استخدم ورقة أولى بسبعة أعمدة وحتى 5000 طالب.');$reader->setLoadSheetsOnly($infos[0]['worksheetName']);$book=$reader->load($file['tmp_name']);$data=$book->getSheet(0)->toArray(null,false,false,false);
 }else throw new RuntimeException('الامتداد المدعوم CSV أو XLSX فقط.');
 if(!$data)throw new RuntimeException('ملف فارغ.');$header=array_map(fn($v)=>trim((string)$v),array_shift($data));$header[0]=preg_replace('/^\x{FEFF}/u','',$header[0]);if($header!==['code','name','department','stage','shift','section','needs_access'])throw new RuntimeException('استخدم قالب الأعمدة السبعة كما هو.');
 $count=0;foreach($data as $row){if(!array_filter($row,fn($v)=>$v!==null&&trim((string)$v)!==''))continue;if(count($row)!==7||++$count>5000)throw new RuntimeException('صف غير صحيح أو تجاوز عدد الطلبة.');[$code,$name,$dept,$stage,$shift,$section,$access]=array_map(fn($v)=>trim((string)$v),$row);
  $department=rows('SELECT id FROM departments WHERE institution_id=? AND name=?',[inst(),$dept])[0]??null;$stageRow=$department?rows('SELECT id FROM stages WHERE institution_id=? AND department_id=? AND name=?',[inst(),$department['id'],$stage])[0]??null:null;
  if(!$stageRow)throw new RuntimeException('قسم أو مرحلة غير معرفين في صف الطالب '.$code);
  run('INSERT INTO students(institution_id,year_id,department_id,stage_id,code,name,shift,section_name,needs_access,active) VALUES(?,?,?,?,?,?,?,?,?,1)',[inst(),year_id(),$department['id'],$stageRow['id'],txt($code,60),txt($name),enumv($shift,['صباحي','مسائي']),txt($section,80,false),intv($access,0,1)]);
 }if(!$count)throw new RuntimeException('لا توجد سجلات طلاب في الملف.');return $count;
}
const REPORT_TYPES=['map'=>'خريطة القاعة','list'=>'قائمة القاعة','summary'=>'الخريطة الشاملة','monitors'=>'خريطة المراقبين','workload'=>'ملخص المراقبات','card'=>'بطاقة الطالب','conflicts'=>'تقرير التعارضات','capacity'=>'تقرير السعة'];
function report_rows(array $data,string $type,int $room=0,int $student=0):array {
 $students=array_values(array_filter($data['students'],fn($s)=>(!$room||(int)$s['room_id']===$room)&&(!$student||(int)$s['student_id']===$student)));
 if(in_array($type,['map','list','card'],true)){$rows=[['الرمز','اسم الطالب','القسم','المرحلة','المادة','القاعة','البناية','الطابق','المقعد','موعد الامتحان']];foreach($students as $s)$rows[]=[$s['code'],$s['name'],$s['department'],$s['stage'],$s['subject'],$s['room_code'],$s['building'],$s['floor_name'],$s['label'],$data['period']['starts_at']];return $rows;}
 if($type==='monitors'){$rows=[['المراقب','اللقب','القاعة','البناية','التكليف','الموعد']];foreach($data['monitors'] as $s)if(!$room||(int)$s['room_id']===$room)$rows[]=[$s['name'],$s['academic_title'],$s['room_code'],$s['building'],$s['role']==='chief'?'رئيس قاعة':'مراقب',$data['period']['starts_at']];return $rows;}
 if($type==='workload'){$rows=[['المراقب','عدد التكليفات','الدقائق المسندة','الدقائق السابقة','المجموع']];foreach(rows('SELECT i.id,i.name,i.baseline_minutes,COUNT(a.id) AS assignments,COALESCE(SUM(TIMESTAMPDIFF(MINUTE,p.starts_at,p.ends_at)),0) AS minutes FROM invigilators i LEFT JOIN invigilation_assignments a ON a.invigilator_id=i.id LEFT JOIN exam_periods p ON p.id=a.period_id WHERE i.institution_id=? GROUP BY i.id,i.name,i.baseline_minutes ORDER BY minutes,i.id',[inst()]) as $r)$rows[]=[$r['name'],$r['assignments'],$r['minutes'],$r['baseline_minutes'],(int)$r['minutes']+(int)$r['baseline_minutes']];return $rows;}
 if($type==='conflicts'){$rows=[['المستوى','التفصيل']];foreach(['errors'=>'خطأ','warnings'=>'ملاحظة'] as $key=>$label)foreach($data['issues'][$key] as $issue)$rows[]=[$label,$issue];if(count($rows)===1)$rows[]=['فحص','لا توجد مخالفات حسب القيود المسجلة.'];return $rows;}
 if($type==='capacity'&&isset($data['capacity'])){$out=[['القاعة','البناية','المواقع الهندسية','المقاعد النشطة','السعة المسموحة','المشغول في الفترة','المتاح للفترة','حالة القاعة']];foreach($data['capacity'] as $r)if(!$room||(int)$r['id']===$room)$out[]=[$r['code'],$r['building'],$r['physical_seats'],$r['active_seats'],$r['capacity'],$r['used'],$r['remaining'],['available'=>'متاحة','reserve'=>'احتياطية','booked'=>'محجوزة'][$r['status']]];return $out;}
 $rows=$type==='capacity'?[['القاعة','البناية','المقاعد الفعلية','المقاعد النشطة','السعة المسموحة','المشغول','المتاح ضمن السعة']]:[['القاعة','عدد الطلبة','المواد','المراقبون','الموعد']];
 foreach($data['rooms'] as $r){if($room&&(int)$r['id']!==$room)continue;$people=array_values(array_filter($data['students'],fn($s)=>$s['room_id']==$r['id']));$staff=array_filter($data['monitors'],fn($s)=>$s['room_id']==$r['id']);$seats=$data['seats'][$r['id']]??[];$active=count(array_filter($seats,fn($s)=>$s['state']==='active'));
  $rows[]=$type==='capacity'?[$r['code'],$r['building'],count($seats),$active,$r['capacity'],count($people),max(0,min($r['capacity'],$active)-count($people))]:[$r['code'],count($people),implode('، ',array_unique(array_column($people,'subject'))),implode('، ',array_column($staff,'name')),$data['period']['starts_at']];
 }return $rows;
}
function report_html(array $data,string $type,int $room=0,int $student=0):string {
 $title=REPORT_TYPES[$type]??'تقرير';$html='<h1>'.h($data['institution']['name']).' — نظام مقعد</h1><h2>'.h($title).' · '.h($data['period']['name']).'</h2><p>'.h($data['year']['name'].' / '.$data['period']['exam_round'].' / '.$data['period']['starts_at'].' — '.$data['period']['ends_at']).' · '.h($data['period']['status']==='approved'?'معتمد':'مسودة غير معتمدة').'</p>';
 if($type==='map'){
  $number=0;foreach($data['rooms'] as $r){if($room&&(int)$r['id']!==$room)continue;if($number++)$html.='<pagebreak /><div class="page-break"></div>';
   $html.='<h2>قاعة '.h($r['code'].' — '.$r['name']).'</h2><p>'.h($r['building'].' / الطابق '.$r['floor_name'].' / المدخل: '.$r['entrance'].' / السبورة: '.($r['board']==='north'?'أعلى الخريطة':'أسفل الخريطة')).'</p>';
   $assigned=[];foreach($data['students'] as $s)if($s['room_id']==$r['id'])$assigned[$s['seat_id']]=$s;$positions=[];foreach($data['seats'][$r['id']]??[] as $s)$positions[$s['row_no'].':'.$s['col_no']]=$s;
   $html.='<table class="seat-report" dir="ltr">';if($r['board']==='north')$html.='<tr><th colspan="'.(int)$r['cols_count'].'">السبورة / مقدمة القاعة</th></tr>';
   for($row=1;$row<=$r['rows_count'];$row++){$html.='<tr>';for($col=1;$col<=$r['cols_count'];$col++){$s=$positions[$row.':'.$col]??null;$a=$s?($assigned[$s['id']]??null):null;$html.='<td dir="rtl">'.(!$s?'':($s['state']==='aisle'?'ممر':($s['state']==='disabled'?'مقعد معطل':('<b>'.h($s['label']).'</b><br>'.($a?h($a['name']).'<br>'.h($a['code']).'<br><small>'.h($a['subject']).'</small>':'شاغر'))))).'</td>';}$html.='</tr>';}
   if($r['board']==='south')$html.='<tr><th colspan="'.(int)$r['cols_count'].'">السبورة / مقدمة القاعة</th></tr>';$html.='</table>';
  }return $html;
 }
 $rows=report_rows($data,$type,$room,$student);$html.='<table><thead><tr>';foreach(array_shift($rows) as $v)$html.='<th>'.h($v).'</th>';$html.='</tr></thead><tbody>';foreach($rows as $row){$html.='<tr>';foreach($row as $v)$html.='<td>'.h($v).'</td>';$html.='</tr>';}$html.='</tbody></table>';return $html;
}
function pdf_download(array $data,string $type,int $room,int $student,string $paper):never {
 if(!class_exists(\Mpdf\Mpdf::class))throw new RuntimeException('مكتبة PDF غير مثبتة؛ اتبع دليل التثبيت.');
 $temp=dirname(__DIR__).'/storage/mpdf';if(!is_dir($temp))mkdir($temp,0700,true);
 $pdf=new \Mpdf\Mpdf(['mode'=>'utf-8','format'=>$paper==='A3'?'A3-L':'A4-L','tempDir'=>$temp,'default_font'=>'dejavusans','autoScriptToLang'=>true,'autoLangToFont'=>true,'margin_left'=>10,'margin_right'=>10,'margin_top'=>12,'margin_bottom'=>14]);
 $pdf->SetDirectionality('rtl');$pdf->SetTitle('نظام مقعد — '.REPORT_TYPES[$type]);$pdf->SetHTMLFooter('<div style="text-align:center;font-size:9px">نظام مقعد · {PAGENO} / {nbpg}</div>');
 $pdf->WriteHTML('body{font-family:dejavusans;font-size:10pt;color:#183d31}h1{font-size:17pt;color:#087b53}h2{font-size:13pt}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{border:1px solid #bed9cb;padding:7px;text-align:right;word-wrap:break-word}th{background:#edf7f0}.seat-report td{height:50px;text-align:center;font-size:9pt}small{font-size:8pt}',\Mpdf\HTMLParserMode::HEADER_CSS);
 $pdf->WriteHTML(report_html($data,$type,$room,$student),\Mpdf\HTMLParserMode::HTML_BODY);$pdf->Output('maqad-report.pdf',\Mpdf\Output\Destination::DOWNLOAD);exit;
}
