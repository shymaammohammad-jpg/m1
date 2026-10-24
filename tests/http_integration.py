# Run only against an empty, isolated test installation. See tests/README.md.
import support
from support import *
if sql('SHOW TABLES'):raise RuntimeError('The integration database must be empty; no data was changed.')
check('تهيئة النظام' in get(),'install page')
r=post({'action':'install','institution':'كلية مقعد للاختبار','university':'جامعة الاختبار','year_name':'2026-2027','username':'admin','password':password})
check('اكتمل إعداد' in r,'installation')
check('لوحة التحكم' in post({'action':'login','username':'admin','password':password}),'admin login')
for name in ['الإحصاء','الحاسبات']:check('تم حفظ' in post({'action':'save','kind':'department','name':name},'?page=structure'),'department '+name)
d1=eid('departments','الإحصاء');d2=eid('departments','الحاسبات')
for dept in [d1,d2]:check('تم حفظ' in post({'action':'save','kind':'stage','name':'الأولى','department_id':dept},'?page=structure'),'stage')
t1=sql('SELECT id FROM stages WHERE department_id='+d1);t2=sql('SELECT id FROM stages WHERE department_id='+d2)
for name,dept,stage in [('رياضيات',d1,t1),('برمجة',d2,t2)]:check('تم حفظ' in post({'action':'save','kind':'subject','name':name,'department_id':dept,'stage_id':stage},'?page=structure'),'subject')
b1=eid('subjects','رياضيات');b2=eid('subjects','برمجة')
for code,status in [('101','available'),('102','available'),('103','reserve')]:
 check('تم حفظ' in post({'action':'save','kind':'room','name':'قاعة '+code,'code':code,'building':'الرئيسية','floor_name':'الأرضي','rows_count':'5','cols_count':'6','capacity':'30','status':status,'board':'north','entrance':'أمام اليمين','required_monitors':'2'},'?page=rooms'),'room '+code)
r1=eid('rooms','قاعة 101');r2=eid('rooms','قاعة 102');r3=eid('rooms','قاعة 103')
seatdata={'action':'seats','room_id':r1}
for sid in sql('SELECT id FROM room_seats WHERE room_id='+r1).splitlines():seatdata['seat_state['+sid+']']='active'
first=sql('SELECT MIN(id) FROM room_seats WHERE room_id='+r1);second=str(int(first)+1)
seatdata['seat_state['+first+']']='disabled';seatdata['seat_state['+second+']']='aisle'
for sid in [str(int(first)+2),str(int(first)+3)]:seatdata['accessible['+sid+']']='1'
check('حُفظت الممرات' in post(seatdata,'?page=room&id='+r1),'visual seat editing')
head=['code','name','department','stage','shift','section','needs_access'];buf=io.StringIO();w=csv.writer(buf);w.writerow(head)
for i in range(1,75):w.writerow([f'S{i:03}','طالب اختبار '+str(i),'الإحصاء' if i<=37 else 'الحاسبات','الأولى','صباحي','أ','1' if i in [1,2] else '0'])
blob=buf.getvalue().encode('utf-8-sig')
check('تم استيراد 74' in upload('import-students','students_file','students.csv',blob,'?page=students'),'CSV import')
check(sql('SELECT COUNT(*) FROM students')=='74','import count')
check('سجل مكرر' in upload('import-students','students_file','students.csv',blob,'?page=students'),'duplicate import rejected')
check(sql('SELECT COUNT(*) FROM students')=='74','failed import atomic')
for i in range(1,9):check('تم حفظ' in post({'action':'save','kind':'invigilator','name':'مراقب '+str(i),'academic_title':'مدرس','department_id':d1,'duty':'observer' if i>7 else 'any','baseline_minutes':'600' if i==1 else '0','active':'1'},'?page=invigilators'),'invigilator')
check('سُجل الاستثناء' in post({'action':'availability','invigilator_id':'2','starts_at':'2026-11-01T08:00','ends_at':'2026-11-01T13:00','reason':'التزام رسمي'},'?page=invigilators'),'official exception')
period={'action':'period','name':'امتحان نهائي','starts_at':'2026-11-01T09:00','ends_at':'2026-11-01T11:00','exam_round':'الأول','term_name':'الأول','study_system':'بولونيا','adjacency':'horizontal','grouping':'subject'}
check('حُفظ الجدول' in post(period,'?page=periods'),'exam period')
pid=eid('exam_periods','امتحان نهائي');url='?page=exam&id='+pid
for bid in [b1,b2]:check('رُشح 37' in post({'action':'enroll','period_id':pid,'subject_id':bid},url),'enrollment')
check('لا يمكن إسناد' not in get(url),'exam render')
check('لم يخصص مقعد' in post({'action':'approve','period_id':pid},url),'approval before distribution blocked')
check('وُزع الطلبة' in post({'action':'generate','period_id':pid},url),'student solver')
check(sql('SELECT COUNT(*) FROM seating_assignments WHERE period_id='+pid)=='74','all seated')
check(sql('SELECT COUNT(DISTINCT s.room_id) FROM seating_assignments a JOIN room_seats s ON s.id=a.seat_id WHERE a.period_id='+pid)=='3','reserve opened')
check(sql("SELECT COUNT(*) FROM seating_assignments a JOIN room_seats s ON s.id=a.seat_id WHERE s.state<>'active'")=='0','no disabled or aisle seats')
check(sql('SELECT COUNT(*) FROM seating_assignments a JOIN room_seats q ON q.id=a.seat_id JOIN students s ON s.id=a.student_id WHERE s.needs_access=1 AND q.accessible=0')=='0','accessible seats respected')
map1=sql('SELECT student_id,seat_id FROM seating_assignments WHERE period_id='+pid+' ORDER BY student_id')
check('وُزع الطلبة' in post({'action':'generate','period_id':pid},url),'repeat generation')
check(sql('SELECT student_id,seat_id FROM seating_assignments WHERE period_id='+pid+' ORDER BY student_id')==map1,'deterministic saved distribution')
check('المراقبين' in post({'action':'approve','period_id':pid},url) and sql('SELECT status FROM exam_periods WHERE id='+pid)=='draft','approval missing monitors blocked')
check('وُزع المراقبون' in post({'action':'monitors','period_id':pid},url),'monitor solver')
check(sql('SELECT COUNT(*) FROM invigilation_assignments WHERE period_id='+pid)=='6','monitor coverage')
check(sql('SELECT COUNT(*) FROM invigilation_assignments WHERE period_id='+pid+' AND invigilator_id IN (1,2)')=='0','workload and availability honored')
# invalid moves must leave original map intact
student=sql('SELECT MIN(student_id) FROM seating_assignments WHERE period_id='+pid)
check('مقعد غير صالح' in post({'action':'move','period_id':pid,'student_id':student,'seat_id':first},url),'move to disabled rejected')
check(sql('SELECT student_id,seat_id FROM seating_assignments WHERE period_id='+pid+' ORDER BY student_id')==map1,'invalid move rollback')
empty=sql('SELECT q.id FROM room_seats q LEFT JOIN seating_assignments a ON a.seat_id=q.id AND a.period_id='+pid+" WHERE q.state='active' AND a.id IS NULL ORDER BY q.id LIMIT 1")
# choose non-access student, preserve capacity by moving within same room
student=sql('SELECT a.student_id FROM seating_assignments a JOIN room_seats q ON q.id=a.seat_id JOIN students s ON s.id=a.student_id WHERE q.room_id=(SELECT room_id FROM room_seats WHERE id='+empty+') AND s.needs_access=0 LIMIT 1')
check('تم النقل' in post({'action':'move','period_id':pid,'student_id':student,'seat_id':empty},url),'valid manual move')
check(sql('SELECT COUNT(*) FROM invigilation_assignments WHERE period_id='+pid)=='0','manual move invalidates staff draft')
check('وُزع المراقبون' in post({'action':'monitors','period_id':pid},url),'reassign monitors')
# replace one monitor with currently unused and available staff
assignment=sql('SELECT MIN(id) FROM invigilation_assignments WHERE period_id='+pid)
check('حُفظ البديل' in post({'action':'replace-monitor','period_id':pid,'assignment_id':assignment,'invigilator_id':'1'},url),'replace observer/head with eligible substitute')
check('اعتُمدت الخريطة' in post({'action':'approve','period_id':pid},url),'approve and freeze')
check('معتمدة ومقفلة' in post({'action':'generate','period_id':pid},url),'approved map immutable')
check(sql('SELECT status FROM exam_periods WHERE id='+pid)=='approved','approved status')
# Another period cannot enroll the same student in an overlapping time.
check('حُفظ الجدول' in post({**period,'name':'فترة متعارضة','starts_at':'2026-11-01T10:00','ends_at':'2026-11-01T12:00'},'?page=periods'),'overlapping period setup')
pid2=eid('exam_periods','فترة متعارضة')
check('فترة متداخلة' in post({'action':'enroll','period_id':pid2,'subject_id':b1,'student_id':'1'},'?page=exam&id='+pid2),'student overlap blocked')
# Portal tokens are personal and see only approved own records.
r=post({'action':'token','kind':'student','id':'1'},'?page=students');token=re.search(r'(?<![a-f0-9])([a-f0-9]{48})(?![a-f0-9])',r)[1]
portal=client();out=post({'action':'portal','portal_kind':'student','lookup_code':token},'?page=portal',portal)
check('طالب اختبار 1' in out and 'رقم المقعد' in out and 'طالب اختبار 2' not in out,'private student portal')
r=post({'action':'token','kind':'invigilator','id':'1'},'?page=invigilators');monitor_token=re.search(r'(?<![a-f0-9])([a-f0-9]{48})(?![a-f0-9])',r)[1]
check('تكليفات المراقبة' in post({'action':'portal','portal_kind':'invigilator','lookup_code':monitor_token},'?page=portal',client()),'monitor portal')
# Every printed report and downloadable format is exercised after dependencies installed.
for type_ in ['map','list','summary','monitors','workload','card','conflicts','capacity']:
 check('Fatal error' not in get('?page=reports&period_id='+pid+'&type='+type_),'HTML report '+type_)
 pdf=get('?page=reports&period_id='+pid+'&type='+type_+'&format=pdf',raw=True)
 check(pdf.startswith(b'%PDF-'),'PDF '+type_)
 xlsx=get('?page=reports&period_id='+pid+'&type='+type_+'&format=xlsx',raw=True)
 check(xlsx.startswith(b'PK') and 'xl/workbook.xml' in zipfile.ZipFile(io.BytesIO(xlsx)).namelist(),'XLSX '+type_)
# Test XLSX export/import roundtrip with additional academic year so it does not duplicate existing list.
export=get('?download=students',raw=True);check(export.startswith(b'PK'),'student export Excel')
check('تم حفظ' in post({'action':'save','kind':'year','name':'2027-2028'},'?page=structure'),'new year')
y2=eid('academic_years','2027-2028');post({'action':'year','year_id':y2})
check('تم استيراد 74' in upload('import-students','students_file','students.xlsx',export,'?page=students'),'XLSX import')
post({'action':'year','year_id':'1'})
# Create reader and planner accounts; permissions checked on server.
for user,role in [('reader','viewer'),('planner','planner')]:check('حُفظ الحساب' in post({'action':'user','username':user,'password':password,'role':role},'?page=settings'),'create '+role)
for user in ['reader','planner']:
 op=client();post({'action':'login','username':user,'password':password},op=op)
 check('صلاحية' in post({'action':'reopen','period_id':pid,'reason':'محاولة اختبار'},url,op),'role cannot reopen '+user)
 if user=='reader':check('صلاحية' in post({'action':'save','kind':'department','name':'ممنوع'},'?page=structure',op),'reader cannot write')
check('انتهت صلاحية' in post({'action':'settings','name':'bad','university':'','csrf':'bad'},'?page=settings'),'CSRF')
# Tenant isolation.
check('أُنشئت المؤسسة' in post({'action':'new-institution','name':'مؤسسة مستقلة','university':'جامعة مستقلة','year_name':'2026-2027','username':'otheradmin','password':password},'?page=settings'),'new institution')
other=client();post({'action':'login','username':'otheradmin','password':password},op=other)
check('السجل غير موجود' in get('?page=exam&id='+pid,other),'cross institution read blocked')
check('السجل غير موجود' in post({'action':'generate','period_id':pid},'?page=exam&id='+pid,other),'cross institution mutation blocked')
# Backup tampering rejected; restore is transactional and leaves accounts/audit untouched.
backup=get('?download=backup',raw=True);envelope=json.loads(backup);check(envelope.get('signature') is not None,'signed backup')
before=sql('SELECT COUNT(*) FROM students WHERE institution_id=1')
check('تم حفظ' in post({'action':'save','kind':'student','name':'مؤقت','code':'TEMP','department_id':d1,'stage_id':t1,'shift':'صباحي','section_name':'','active':'1'},'?page=students'),'temporary data before restore')
bad=dict(envelope);bad['payload']=bad['payload']+' '
check('بصمة النسخة' in upload('restore-backup','backup_file','bad.json',json.dumps(bad).encode(),'?page=settings',{'confirmed':'1'}),'tampered backup rejected')
check(sql('SELECT COUNT(*) FROM students WHERE institution_id=1')==str(int(before)+1),'tampered restore no mutation')
check('استُعيدت بيانات' in upload('restore-backup','backup_file','backup.json',backup,'?page=settings',{'confirmed':'1'}),'restore succeeds')
check(sql('SELECT COUNT(*) FROM students WHERE institution_id=1')==before,'restored domain count')
check(sql('SELECT COUNT(*) FROM users WHERE institution_id=1')=='3','accounts preserved')
check(sql('SELECT COUNT(*) FROM students WHERE institution_id=1 AND portal_hash IS NOT NULL')=='0','portal tokens revoked on restore')
check('رمز الاستعلام غير صالح' in post({'action':'portal','portal_kind':'student','lookup_code':token},'?page=portal',client()),'old token invalid after restore')
for page in ['dashboard','structure','rooms','students','lookup','periods','maps','invigilators','reports','settings','audit']:
 body=get('?page='+page);check('Fatal error' not in body and 'Warning:' not in body and '<html lang="ar"' in body,'page '+page)
check('دخول الإدارة' in post({'action':'logout'}),'logout')
print(f'PASS: {support.count} HTTP/MariaDB/file/portal checks')
