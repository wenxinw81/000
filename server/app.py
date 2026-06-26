import os
import uuid
import sqlite3
import sys
from pathlib import Path
from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS
from license_core import get_machine_code, load_license, verify_license_code

# 获取当前工作目录（可能被改变）
current_dir = os.getcwd()
print(f"当前工作目录: {current_dir}")

# 获取当前执行的Python脚本的绝对路径
script_path = os.path.abspath(__file__)
print(f"脚本绝对路径: {script_path}")

def enforce_license_or_exit():
    result = verify_license_code(get_machine_code(), load_license(Path(current_dir)))
    if not result.ok:
        print("=" * 60)
        print("软件未授权，app 服务已拒绝启动。")
        print(f"原因: {result.message}")
        print(f"本机机器码: {get_machine_code()}")
        print("请通过注册窗口完成授权后再启动。")
        print("=" * 60)
        sys.exit(3)

# 配置
#app.static_url_path = '/dzspapp'
app = Flask(__name__,static_url_path = '/dzsp')
CORS(app)  # 允许跨域请求
DATABASE = current_dir+'/dzsp.db'
UPLOAD_FOLDER = current_dir+'/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.static_folder = current_dir+'/dzspapp'


# 确保上传目录存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 数据库连接管理
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # 启用行工厂，使查询结果可通过列名访问
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# 数据库初始化
def init_db():
    with app.app_context():
        db = get_db()
        # 创建目标表
        db.execute('''
        CREATE TABLE IF NOT EXISTS target (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pid INTEGER,
            name TEXT NOT NULL,
            cmd TEXT NOT NULL,
            txturl TEXT NOT NULL,
            imgurl TEXT NOT NULL,
            mp4url TEXT NOT NULL,
            videourl TEXT NOT NULL,
            viewpoint TEXT NOT NULL,
            docurl TEXT NOT NULL,
            pdfurl TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        db.commit()

# 检查文件扩展名是否允许
def allowed_file(filename):
    return True
    # return '.' in filename and \
    #        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 获取某个节点下所有儿子
@app.route('/api/targetchild/<int:tid>', methods=['GET'])
def get_targetchild(tid):
    db = get_db()
    cursor = db.execute('SELECT * FROM target WHERE pid = ? ORDER BY created_at DESC', (tid,))
    pin = cursor.fetchall()
    if pin is None:
        return jsonify({'error': '目标不存在'}), 404
    target = [dict(row) for row in pin]
    return jsonify(target)

# 获取目标列表
@app.route('/api/target', methods=['GET'])
def get_target():
    db = get_db()
    cursor = db.execute('SELECT * FROM target ORDER BY created_at DESC')
    target = [dict(row) for row in cursor.fetchall()]
    return jsonify(target)

# 获取单个目标详情
@app.route('/api/target/<int:tid>', methods=['GET'])
def get_target_detail(tid):
    db = get_db()
    cursor = db.execute('SELECT * FROM target WHERE id = ?', (tid,))
    pin = cursor.fetchone()
    if pin is None:
        return jsonify({'error': '目标不存在'}), 404
    
    # 获取关联图片
    # image_cursor = db.execute('SELECT * FROM images WHERE tid = ?', (tid,))
    # images = [dict(row) for row in image_cursor.fetchall()]
    
    # result = dict(pin)
    # result['images'] = images
    return jsonify(pin)

# 添加新目标
@app.route('/api/target', methods=['POST'])
def add_target():
    if not request.form or not request.form.get('name') :
        return jsonify({'error': '名称为必填项'}), 400
    
    db = get_db()
    
    # 插入目标记录
    tid = db.execute(
        'INSERT INTO target (pid, name, cmd,txturl,imgurl,mp4url,videourl,viewpoint,docurl,pdfurl) VALUES (?, ?, ?, ?,?, ?, ?, ?,?,?)',
        (request.form['pid'], 
         request.form['name'], request.form['cmd'], request.form['txturl'], request.form['imgurl'], 
         request.form['mp4url'],request.form['videourl'],request.form['viewpoint'], request.form['docurl'], request.form['pdfurl'])
    ).lastrowid
    
    # # 处理图片上传
    # if 'images' in request.files:
    #     files = request.files.getlist('images')
    #     for file in files:
    #         if file and allowed_file(file.filename):
    #             # 生成唯一文件名
    #             filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
    #             filepath = os.path.join(UPLOAD_FOLDER, filename)
    #             file.save(filepath)
                
    #             # 保存图片记录
    #             db.execute(
    #                 'INSERT INTO images (tid, url) VALUES (?, ?)',
    #                 (tid, filename)
    #             )
    
    db.commit()
    return jsonify({'status': 'success', 'tid': tid}), 201

# 更新目标
@app.route('/api/target/<int:tid>', methods=['PUT'])
def update_target(tid):
    db = get_db()
    
    # 检查目标是否存在
    cursor = db.execute('SELECT * FROM target WHERE id = ?', (tid,))
    if cursor.fetchone() is None:
        return jsonify({'error': '目标不存在'}), 404
    
    # 更新目标基本信息
    db.execute(
        'UPDATE target SET pid = ?, name = ?, cmd = ?, txturl = ?, imgurl = ?, mp4url = ?, videourl = ?, viewpoint = ?, docurl = ?, pdfurl = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (request.form['pid'], request.form['name'], 
         request.form['cmd']
         , request.form['txturl'], request.form['imgurl']
          , request.form['mp4url'], request.form['videourl'], request.form['viewpoint'], request.form['docurl'], request.form['pdfurl'], tid)
    )
    
    db.commit()
    return jsonify({'status': 'success'})

# 删除目标
@app.route('/api/target/<int:tid>', methods=['DELETE'])
def delete_target(tid):
    db = get_db()
    
    # 检查目标是否存在
    cursor = db.execute('SELECT * FROM target WHERE id = ?', (tid,))
    if cursor.fetchone() is None:
        return jsonify({'error': '目标不存在'}), 404
    
    # 删除关联图片文件
    image_cursor = db.execute('SELECT txturl,imgurl,mp4url,docurl,pdfurl FROM target WHERE id = ?', (tid,))
    item = image_cursor.fetchone()
    for image in item:
        try:
            if not(image=='' or (image is None)):
                os.remove(os.path.join(UPLOAD_FOLDER,image))
        except Exception as e:
            print(f"删除文件失败: {e}")
    
    # 删除目标(会级联删除关联的图片记录)
    db.execute('DELETE FROM target WHERE id = ?', (tid,))
    db.commit()
    return jsonify({'status': 'success'})

# 上传文件
@app.route('/api/file', methods=['POST'])
def add_file():
    urls=[]
    if 'files' in request.files:
        files = request.files.getlist('files')
        for file in files:
            if file and allowed_file(file.filename):
                # 生成唯一文件名
                filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                urls.append(filename)
    return jsonify({'status': 'success','urls':urls}), 201

# 删除文件
@app.route('/api/file/<string:url>', methods=['DELETE'])
def delete_file(url):
    # 删除文件
    try:
        os.remove(os.path.join(UPLOAD_FOLDER,url))
    except Exception as e:
        return jsonify({'error': f'删除图片文件失败: {str(e)}'}), 500
    
    return jsonify({'status': 'success'})

# 提供图片访问
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# 登录验证，暂时写死
@app.route('/api/login', methods=['POST'])
def login():
    if not request.form or not request.form.get('name') or not request.form.get('password'):
        return jsonify({'error': '账号密码为必填项'}), 400
    name=request.form.get('name')
    password=request.form.get('password')
    if name=="admin" and password=="admin123":
        return jsonify({'status': 'success','username':name,"access_token":"df3df43f433"})
    else:
        return jsonify({'status': 'fail'}), 401

# 应用入口
if __name__ == '__main__':
    enforce_license_or_exit()
    init_db()  # 初始化数据库
    app.run(debug=False, host='0.0.0.0', port=5000)
