"""

 SCHOOL PRO MAX V2 - + شات الطلبة + الواجبات
 المتحكم: المدرس يقدر يقفل الشات ويمسح الرسايل

"""

from fastapi import FastAPI, Request, UploadFile, Form, File, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import sqlite3, os, shutil, hashlib, json, uuid, asyncio
from datetime import date, datetime
import matplotlib.pyplot as plt
import io, base64

app = FastAPI(title="School Pro Max V2")

# ============= 1. الاعدادات =============
UPLOAD_DIR = "uploads"; os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
DB_NAME = "school_max_v2.db"

connected_users = {} # {user_id: websocket}
chat_rooms = {} # {class_id: [user_ids]}

def hash_pass(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db(); c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY, name TEXT, logo TEXT, theme TEXT DEFAULT 'light', chat_enabled INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY, username TEXT, password TEXT);
    CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, name TEXT, phone TEXT UNIQUE, password TEXT, school_id INTEGER, subject TEXT);
    CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, name TEXT, phone TEXT UNIQUE, password TEXT, school_id INTEGER, class_id INTEGER, parent_phone TEXT, points INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY, name TEXT, teacher_id INTEGER, school_id INTEGER, student_count INTEGER);
    CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, student_id INTEGER, class_id INTEGER, date TEXT, is_present INTEGER);
    CREATE TABLE IF NOT EXISTS excuses (id INTEGER PRIMARY KEY, student_id INTEGER, reason TEXT, image_path TEXT, status TEXT, date TEXT);
    CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, user_id INTEGER, user_type TEXT, message TEXT, is_read INTEGER, date TEXT);
    CREATE TABLE IF NOT EXISTS friends (id INTEGER PRIMARY KEY, student_id INTEGER, friend_id INTEGER);
    CREATE TABLE IF NOT EXISTS grades (id INTEGER PRIMARY KEY, student_id INTEGER, subject TEXT, grade REAL, term TEXT, date TEXT);

    -- جداول جديدة
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER,
        sender_id INTEGER,
        sender_type TEXT,
        message TEXT,
        file_path TEXT,
        date TEXT,
        FOREIGN KEY (class_id) REFERENCES classes(id)
    );
    CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER,
        teacher_id INTEGER,
        title TEXT,
        description TEXT,
        file_path TEXT,
        due_date TEXT,
        created_date TEXT
    );
    CREATE TABLE IF NOT EXISTS homework_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        homework_id INTEGER,
        student_id INTEGER,
        file_path TEXT,
        submit_date TEXT,
        grade REAL,
        note TEXT
    );
    """)
    c.execute("INSERT OR IGNORE INTO admins VALUES (1, 'admin',?)", (hash_pass("admin"),))
    c.execute("INSERT OR IGNORE INTO schools VALUES (1, 'مدرسة المستقبل', 'logo.png', 'light', 1)")
    c.execute("INSERT OR IGNORE INTO teachers VALUES (1,'أستاذ محمد','0100',?,1,'رياضيات')", (hash_pass("123"),))
    c.execute("INSERT OR IGNORE INTO classes VALUES (1,'1/1',1,1,3)")
    for i in range(1,4): c.execute("INSERT OR IGNORE INTO students VALUES (?,?,?,?,?,?, '0109', 100)", (i,f"طالب {i}",f"011{i}",hash_pass("123"),1,1))
    conn.commit(); conn.close()
init_db()
# ============= 2. التصميم =============
def get_css():
    return """<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap');
    :root{--dark:#0A2463;--white:#FFF;--light:#E8F1FF;--radius:16px}
    *{font-family:'Cairo',sans-serif} body{background:#f5f7fa;margin:0;direction:rtl}
   .sidebar{width:250px;background:var(--dark);color:white;height:100vh;position:fixed;top:0;right:0;padding:20px}
   .sidebar a{display:block;color:white;padding:12px;margin:8px 0;border-radius:var(--radius);text-decoration:none}
   .main{margin-right:270px;padding:20px}
   .header{background:var(--white);padding:15px;border-radius:var(--radius);margin-bottom:20px}
   .card{background:var(--white);border-radius:var(--radius);padding:20px;margin:15px 0}
   .btn{background:var(--dark);color:var(--white);border:none;border-radius:var(--radius);padding:12px 25px;cursor:pointer}
   .input{background:var(--light);border:none;border-radius:var(--radius);padding:12px;width:95%}
   .chat-box{height:400px;overflow-y:auto;background:var(--light);padding:15px;border-radius:var(--radius)}
   .msg{margin:10px 0;padding:10px;border-radius:10px;max-width:70%}
   .msg.me{background:var(--dark);color:white;margin-right:auto}
   .msg.other{background:white}
   .homework-card{border-right:4px solid var(--dark);padding:15px;margin:10px 0;background:var(--light)}
    </style>"""

# ============= 3. شاشات المدرس PC + Mobile =============

@app.get("/teacher/dashboard/{id}", response_class=HTMLResponse)
def teacher_dashboard(id:int):
    db=get_db(); classes=db.execute("SELECT * FROM classes WHERE teacher_id=?",(id,)).fetchall(); db.close()
    cards="".join([f"<div class='card' onclick=\"location='/teacher/class/{c[0]}/chat'\"><h3>فصل {c[1]}</h3><button class='btn'>الشات</button> <button class='btn' onclick=\"location='/teacher/class/{c[0]}/homework'\">الواجبات</button></div>" for c in classes])
    return f"<html><head>{get_css()}</head><body><div class='sidebar'><h3>👨‍🏫 المدرس</h3></div><div class='main'><div class='header'><h2>أهلاً أستاذ محمد</h2></div>{cards}</div></body></html>"

@app.get("/teacher/class/{class_id}/chat", response_class=HTMLResponse)
def teacher_chat_control(class_id:int):
    db=get_db(); chat_enabled=db.execute("SELECT chat_enabled FROM schools WHERE id=1").fetchone()[0]; db.close()
    toggle_btn = "ايقاف الشات" if chat_enabled else "تشغيل الشات"
    return f"""<html><head>{get_css()}</head><body>
    <div class='main'><div class='header'><h2>التحكم في شات فصل {class_id}</h2>
    <button class='btn' onclick="fetch('/api/chat/toggle')"> {toggle_btn} </button></div>
    <div class='card'><div class='chat-box' id='chatBox'></div>
    <input id='msg' class='input' placeholder='اكتب رسالة كمشرف...'>
    <button class='btn' onclick='sendMsg()'>ارسال</button>
    <button class='btn' style='background:red' onclick='clearChat()'>مسح كل الرسايل</button></div></div>
    <script>
    const ws = new WebSocket(ws://localhost:8000/ws/teacher_{class_id});
    ws.onmessage = (e)=>{const d=JSON.parse(e.data);document.getElementById('chatBox').innerHTML+=<div class='msg other'><b>${d.sender}:</b> ${d.message}</div>};
    function sendMsg(){{ws.send(JSON.stringify({{msg:document.getElementById('msg').value}}));document.getElementById('msg').value=''}}
    function clearChat(){{fetch('/api/chat/clear/{class_id}')}}
    </script></body></html>"""

@app.get("/teacher/class/{class_id}/homework", response_class=HTMLResponse)
def teacher_homework(class_id:int):
    db=get_db(); hw=db.execute("SELECT * FROM homework WHERE class_id=?",(class_id,)).fetchall(); db.close()
    rows="".join([f"<div class='homework-card'><h3>{h[3]}</h3><p>{h[4]}</p><p>التسليم: {h[6]}</p><a href='/teacher/homework/{h[0]}/submissions'>عرض التسليمات</a></div>" for h in hw])
return f"""<html><head>{get_css()}</head><body><div class='main'><div class='header'><h2>الواجبات - فصل {class_id}</h2></div>
    <div class='card'><form action='/api/homework/add' method='post' enctype='multipart/form-data'>
    <input name='title' class='input' placeholder='عنوان الواجب'>
    <textarea name='desc' class='input' placeholder='الوصف'></textarea>
    <input name='due' type='date' class='input'>
    <input name='file' type='file' class='input'>
    <input type='hidden' name='class_id' value='{class_id}'>
    <input type='hidden' name='teacher_id' value='1'>
    <button class='btn'>اضافة واجب</button></form></div>{rows}</div></body></html>"""

# ============= 4. شاشات الطالب =============

@app.get("/student/class/{class_id}/chat", response_class=HTMLResponse)
def student_chat(class_id:int, student_id:int=1):
    return f"""<html><head>{get_css()}</head><body style='max-width:500px;margin:auto'>
    <div class='header'>شات الفصل</div>
    <div class='card'><div class='chat-box' id='chatBox'></div>
    <input id='msg' class='input' placeholder='اكتب رسالة...'>
    <button class='btn' onclick='sendMsg()'>ارسال</button></div>
    <script>
    const ws = new WebSocket(ws://localhost:8000/ws/student_{student_id}_{class_id});
    ws.onmessage = (e)=>{const d=JSON.parse(e.data);document.getElementById('chatBox').innerHTML+=<div class='msg ${d.me?"me":"other"}'><b>${d.sender}:</b> ${d.message}</div>};
    function sendMsg(){{ws.send(JSON.stringify({{msg:document.getElementById('msg').value}}));document.getElementById('msg').value=''}}
    </script></body></html>"""

@app.get("/student/homework", response_class=HTMLResponse)
def student_homework(student_id:int=1):
    db=get_db(); hw=db.execute("SELECT h.*,c.name FROM homework h JOIN classes c ON h.class_id=c.id JOIN students s ON s.class_id=c.id WHERE s.id=?",(student_id,)).fetchall()
    cards="".join([f"<div class='homework-card'><h3>{h[3]}</h3><p>{h[4]}</p><p>المادة: {h[2]}</p><p>اخر معاد: {h[6]}</p><a href='/student/homework/{h[0]}/submit'>تسليم الواجب</a></div>" for h in hw]); db.close()
    return f"<html><head>{get_css()}</head><body style='max-width:500px;margin:auto'><div class='header'>واجباتي</div>{cards}</body></html>"

@app.get("/student/homework/{hw_id}/submit", response_class=HTMLResponse)
def submit_hw_form(hw_id:int): return f"<html><head>{get_css()}</head><body style='max-width:500px;margin:auto'><div class='header'>تسليم الواجب</div><div class='card'><form action='/api/homework/submit' method='post' enctype='multipart/form-data'><input type='file' name='file' class='input'><input type='hidden' name='hw_id' value='{hw_id}'><input type='hidden' name='student_id' value='1'><button class='btn'>تسليم</button></form></div></body></html>"

# ============= 5. WebSocket للشات + التحكم =============

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    connected_users[client_id] = websocket
    parts = client_id.split('_')
    user_type = parts[0]; user_id = parts[1]; class_id = parts[2] if len(parts)>2 else None

    db=get_db()
    try:
        # بعت الرسايل القديمة
        msgs = db.execute("SELECT * FROM chat_messages WHERE class_id=? ORDER BY id DESC LIMIT 50",(class_id,)).fetchall()
        for m in reversed(msgs):
            await websocket.send_text(json.dumps({"sender":m[3],"message":m[4],"me":m[2]==user_id}))

        while True:
            data = await websocket.receive_json()
            msg = data['msg']

            # المدرس بس اللي يقدر يبعت ملفات ويمسح
            sender_name = "أستاذ" if user_type=="teacher" else "طالب"
            db.execute("INSERT INTO chat_messages(class_id,sender_id,sender_type,message,date) VALUES(?,?,?,?,?)",(class_id,user_id,user_type,msg,str(datetime.now())))
            db.commit()
# ابعت لكل الناس في الفصل
            for cid, ws in connected_users.items():
                if class_id in cid:
                    await ws.send_text(json.dumps({"sender":sender_name,"message":msg,"me":cid==client_id}))
    except WebSocketDisconnect:
        del connected_users[client_id]
    finally: db.close()

# ============= 6. API الجديدة =============

@app.get("/api/chat/toggle")
def toggle_chat():
    db=get_db(); status=db.execute("SELECT chat_enabled FROM schools WHERE id=1").fetchone()[0]
    db.execute("UPDATE schools SET chat_enabled=? WHERE id=1",(0 if status else 1,)); db.commit(); db.close()
    return {"status":"toggled"}

@app.get("/api/chat/clear/{class_id}")
def clear_chat(class_id:int):
    db=get_db(); db.execute("DELETE FROM chat_messages WHERE class_id=?",(class_id,)); db.commit(); db.close()
    return {"status":"cleared"}

@app.post("/api/homework/add")
async def add_homework(class_id:int=Form(...), teacher_id:int=Form(...), title:str=Form(...), desc:str=Form(...), due:str=Form(...), file:UploadFile=File(None)):
    path = ""
    if file:
        path=f"{UPLOAD_DIR}/{uuid.uuid4()}_{file.filename}"
        with open(path,"wb") as f: shutil.copyfileobj(file.file,f)
    db=get_db()
    db.execute("INSERT INTO homework(class_id,teacher_id,title,description,file_path,due_date,created_date) VALUES(?,?,?,?,?,?,?)",(class_id,teacher_id,title,desc,path,due,str(date.today())))
    db.commit(); db.close()
    return RedirectResponse(f"/teacher/class/{class_id}/homework", status_code=303)

@app.post("/api/homework/submit")
async def submit_homework(hw_id:int=Form(...), student_id:int=Form(...), file:UploadFile=File(...)):
    path=f"{UPLOAD_DIR}/{uuid.uuid4()}_{file.filename}"
    with open(path,"wb") as f: shutil.copyfileobj(file.file,f)
    db=get_db()
    db.execute("INSERT INTO homework_submissions(homework_id,student_id,file_path,submit_date) VALUES(?,?,?,?)",(hw_id,student_id,path,str(datetime.now())))
    db.commit(); db.close()
    return JSONResponse({"status":"submitted"})

if name=="main":
    import uvicorn
    print("="*60)
    print(" المدرس: http://localhost:8000/teacher/dashboard/1")
    print(" الطالب: http://localhost:8000/student/class/1/chat?student_id=1")
    print("="*60)
    uvicorn.run(app,host="0.0.0.0",port=8000)