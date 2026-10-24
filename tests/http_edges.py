# Run after http_integration.py against the same isolated fixture.
import support
from support import *
# fixture database already belongs to this test run; reset the test admin password without printing it.
subprocess.run([PHP_BIN,'-r',"$c=require getenv('MAQAD_PROJECT_ROOT').'/config.php';$db=new PDO($c['dsn'],$c['user'],$c['password']);$p=json_decode(file_get_contents('php://stdin'),true);$db->prepare('UPDATE users SET password_hash=? WHERE username=?')->execute([password_hash($p,PASSWORD_DEFAULT),'admin']);"],input=json.dumps(password),text=True,check=True,env=CHILD_ENV)
post({'action':'login','username':'admin','password':password})
post({'action':'year','year_id':'1'})
pid=eid('exam_periods','امتحان نهائي');d1=eid('departments','الإحصاء');d2=eid('departments','الحاسبات');t1=sql('SELECT id FROM stages WHERE department_id='+d1);t2=sql('SELECT id FROM stages WHERE department_id='+d2);b1=eid('subjects','رياضيات');r1=eid('rooms','قاعة 101');url='?page=exam&id='+pid
# Safe deletes and referential edits.
check('تم حفظ' in post({'action':'save','kind':'department','name':'قسم مستقل'},'?page=structure'),'create disposable department')
disposable=eid('departments','قسم مستقل')
check('تم حفظ' in post({'action':'save','kind':'department','id':disposable,'name':'قسم معدل'},'?page=structure'),'edit disposable department')
check('تم حذف' in post({'action':'delete','table':'departments','id':disposable},'?page=structure'),'delete unlinked department')
check('ارتباط يمنع الحذف' in post({'action':'delete','table':'departments','id':d1},'?page=structure'),'linked delete rejected')
check(sql('SELECT COUNT(*) FROM departments WHERE id='+d1)=='1','linked data intact')
check('لا يمكن نقلها' in post({'action':'save','kind':'stage','id':t1,'department_id':d2,'name':'الأولى'},'?page=structure'),'stage move guarded')
check('مرتبطة بترشيحات' in post({'action':'save','kind':'subject','id':b1,'department_id':d2,'stage_id':t2,'name':'رياضيات'},'?page=structure'),'subject scope guarded')
# Mid-file error rolls back previously inserted row.
buf=io.StringIO();w=csv.writer(buf);w.writerow(['code','name','department','stage','shift','section','needs_access']);w.writerow(['ROLLBACK-OK','اختبار أول','الإحصاء','الأولى','صباحي','','0']);w.writerow(['ROLLBACK-FAIL','اختبار ثان','قسم غير موجود','الأولى','صباحي','','0'])
check('قسم أو مرحلة غير معرفين' in upload('import-students','students_file','partial.csv',buf.getvalue().encode(),'?page=students'),'partial import rejected')
check(sql("SELECT COUNT(*) FROM students WHERE code='ROLLBACK-OK'")=='0','partial import rollback')
check('S001' in get('?page=lookup&q=S001') and '101' in get('?page=lookup&q=S001'),'student seat search')
# Admin can reopen; approval is removed from public lookup until validated again.
r=post({'action':'token','kind':'student','id':'1'},'?page=students');token=re.search(r'(?<![a-f0-9])([a-f0-9]{48})(?![a-f0-9])',r)[1]
check('رقم المقعد' in post({'action':'portal','portal_kind':'student','lookup_code':token},'?page=portal',client()),'approved portal visible')
check('فُتحت المسودة' in post({'action':'reopen','period_id':pid,'reason':'اختبار الاستعادة'},url),'admin reopen')
check('لا توجد خرائط معتمدة' in post({'action':'portal','portal_kind':'student','lookup_code':token},'?page=portal',client()),'draft hidden from portal')
# Restore previous distribution (student-only snapshot) and regenerate monitors.
version_id=sql("SELECT id FROM map_versions WHERE period_id="+pid+" AND action='توليد خريطة الطلبة' ORDER BY id LIMIT 1")
check('استُعيد التوزيع' in post({'action':'restore-map','period_id':pid,'version_id':version_id},url),'restore prior distribution')
check(sql('SELECT COUNT(*) FROM seating_assignments WHERE period_id='+pid)=='74','restored complete map')
check('وُزع المراقبون' in post({'action':'monitors','period_id':pid},url),'monitor generation after restore')
check('اعتُمدت الخريطة' in post({'action':'approve','period_id':pid},url),'reapprove restored map')
# Back-to-back sessions are allowed, but overlapping rooms may not be reused.
period={'action':'period','name':'تعاقب زمني','starts_at':'2026-11-01T11:00','ends_at':'2026-11-01T13:00','exam_round':'الأول','term_name':'الأول','study_system':'فصلي','adjacency':'none','grouping':'subject','room_ids[]':[r1]}
check('حُفظ الجدول' in post(period,'?page=periods'),'back-to-back period')
pback=eid('exam_periods','تعاقب زمني');backurl='?page=exam&id='+pback
check('رُشح 1' in post({'action':'enroll','period_id':pback,'subject_id':b1,'student_id':'1'},backurl),'same student back-to-back eligible')
check('وُزع الطلبة' in post({'action':'generate','period_id':pback},backurl),'same room back-to-back available')
check('وُزع المراقبون' in post({'action':'monitors','period_id':pback},backurl),'staff back-to-back available')
# New non-conflicting student, but a selected room is physically occupied in overlapping session.
check('تم حفظ' in post({'action':'save','kind':'student','name':'طالب فترة مستقلة','code':'LATE','department_id':d1,'stage_id':t1,'shift':'صباحي','section_name':'','active':'1'},'?page=students'),'new independent candidate')
late=sql("SELECT id FROM students WHERE code='LATE'")
check('حُفظ الجدول' in post({**period,'name':'تداخل قاعة','starts_at':'2026-11-01T09:30','ends_at':'2026-11-01T10:30'},'?page=periods'),'room-overlap period')
pover=eid('exam_periods','تداخل قاعة');overurl='?page=exam&id='+pover
check('رُشح 1' in post({'action':'enroll','period_id':pover,'subject_id':b1,'student_id':late},overurl),'independent enrollment')
check('السعة المتاحة' in post({'action':'generate','period_id':pover},overurl),'overlapping room excluded')
check(sql('SELECT COUNT(*) FROM seating_assignments WHERE period_id='+pover)=='0','no partial map on conflict')
# Carry a subject from a different stage within the same department only with recorded reference.
check('تم حفظ' in post({'action':'save','kind':'stage','name':'الثانية','department_id':d1},'?page=structure'),'carry target stage')
stage2=sql("SELECT id FROM stages WHERE name='الثانية' AND department_id="+d1)
check('تم حفظ' in post({'action':'save','kind':'student','name':'طالب تحميل','code':'CARRY','department_id':d1,'stage_id':stage2,'shift':'صباحي','section_name':'','active':'1'},'?page=students'),'carry student')
carry=sql("SELECT id FROM students WHERE code='CARRY'")
check('غير مؤهل للمادة' in post({'action':'enroll','period_id':pover,'subject_id':b1,'student_id':carry},overurl),'unrecorded cross-stage rejected')
check('رُشح 1' in post({'action':'enroll','period_id':pover,'subject_id':b1,'student_id':carry,'allow_carry':'1','carry_note':'قرار لجنة 15'},overurl),'documented carry accepted')
check(sql('SELECT carry_note FROM exam_candidates WHERE period_id='+pover+' AND student_id='+carry)=='قرار لجنة 15','carry evidence saved')
# DB uniqueness constraints reject duplicated seat/student independently of UI.
query='INSERT INTO seating_assignments(institution_id,period_id,student_id,seat_id) SELECT institution_id,period_id,student_id,seat_id FROM seating_assignments WHERE period_id='+pid+' LIMIT 1'
r=subprocess.run(MYSQL_COMMAND+['-e',query],capture_output=True,text=True,encoding='utf-8')
check(r.returncode!=0 and 'Duplicate entry' in r.stderr,'database unique constraints')
# A malformed, otherwise linked assignment to a non-candidate must be found by validator.
# Check via a rollback-only CLI transaction so the fixture is preserved.
php="""require getenv('MAQAD_PROJECT_ROOT').'/app/bootstrap.php';$_SESSION['institution_id']=1;$p=period(%s);db()->beginTransaction();$seat=rows('SELECT q.id FROM room_seats q LEFT JOIN seating_assignments a ON a.seat_id=q.id AND a.period_id=? WHERE q.institution_id=1 AND a.id IS NULL LIMIT 1',[$p['id']])[0]['id'];run('INSERT INTO seating_assignments(institution_id,period_id,student_id,seat_id) VALUES(1,?,?,?)',[$p['id'],%s,$seat]);$issues=map_issues($p,false);db()->rollBack();echo json_encode($issues,JSON_UNESCAPED_UNICODE);"""%(pid,late)
issues=subprocess.check_output([PHP_BIN,'-r',php],text=True,env=CHILD_ENV)
check('غير مرشحة' in issues,'orphan assignment validator')
# PDF A3 and frozen reporting still work after extra sessions.
check(get('?page=reports&period_id='+pid+'&type=map&format=pdf&paper=A3',raw=True).startswith(b'%PDF-'),'A3 PDF')
for page in ['lookup','structure','rooms','students','periods','maps','invigilators','reports','settings','audit']:
 check('Fatal error' not in get('?page='+page),'post-edge page '+page)
print(f'PASS: {support.count} edge-case checks')
