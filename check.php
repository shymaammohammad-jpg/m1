<?php
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$missing=[];foreach(['pdo','pdo_mysql','mbstring','gd','zip','dom','simplexml','xmlreader','xmlwriter','fileinfo','iconv'] as $extension)if(!extension_loaded($extension))$missing[]=$extension;
if(PHP_VERSION_ID<80200)$missing[]='PHP 8.2+';
if(!is_file(__DIR__.'/vendor/autoload.php'))$missing[]='vendor/autoload.php (run composer install --no-dev)';
if($missing){fwrite(STDERR,"Missing prerequisites: ".implode(', ',$missing)."\n");exit(1);}
require __DIR__.'/vendor/autoload.php';
if(!class_exists(\Mpdf\Mpdf::class)||!class_exists(\PhpOffice\PhpSpreadsheet\Spreadsheet::class)){fwrite(STDERR,"PDF/Excel dependencies missing\n");exit(1);}
if(!is_writable(__DIR__.'/storage')){fwrite(STDERR,"storage/ must be writable by PHP\n");exit(1);}
echo 'Maqad prerequisites OK — PHP '.PHP_VERSION."; PDF and Excel available.\n";
echo 'Memory limit: '.ini_get('memory_limit').'; upload limit: '.ini_get('upload_max_filesize')."\n";
