import firebase_admin
from firebase_admin import credentials, firestore, auth as admin_auth
from flask import Flask, render_template, request, redirect, url_for, session, flash
import requests
import json
import os
import random
import string
from functools import wraps
from datetime import datetime
import uuid

app = Flask(__name__)
app.config.from_object('config.Config')

# Initialize Firebase Admin SDK
if os.path.exists('firebase-adminsdk.json'):
    cred = credentials.Certificate('firebase-adminsdk.json')
else:
    adminsdk_json = os.environ.get('FIREBASE_ADMINSDK_JSON')
    if adminsdk_json:
        try:
            cred_dict = json.loads(adminsdk_json)
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            raise ValueError(f"Failed to parse FIREBASE_ADMINSDK_JSON: {e}")
    else:
        raise ValueError("Firebase Admin credentials not found! Set FIREBASE_ADMINSDK_JSON or add firebase-adminsdk.json.")

firebase_admin.initialize_app(cred)
db = firestore.client()

# Firebase Auth REST API base URL
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"

# =============================================================================
# HELPERS
# =============================================================================

def generate_join_code(length=7):
    """Generate a unique alphanumeric class join code."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        # Ensure it doesn't conflict with existing codes
        existing = db.collection('classes').where('join_code', '==', code).stream()
        if not any(True for _ in existing):
            return code

# =============================================================================
# DECORATORS
# =============================================================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'teacher':
            flash('Access denied. Teachers only.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'student':
            flash('Access denied. Students only.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# =============================================================================
# AUTH ROUTES
# =============================================================================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')

        if role not in ['teacher', 'student']:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('register'))

        try:
            # Create user in Firebase Auth
            user = admin_auth.create_user(email=email, password=password)

            user_data = {
                'name': name,
                'email': email,
                'role': role,
                'created_at': datetime.now().isoformat()
            }
            # Students start with no classes; they join multiple classes after login
            if role == 'student':
                user_data['class_ids'] = []

            db.collection('users').document(user.uid).set(user_data)

            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            api_key = app.config['FIREBASE_WEB_API_KEY']
            url = f"{FIREBASE_AUTH_URL}:signInWithPassword?key={api_key}"
            payload = {"email": email, "password": password, "returnSecureToken": True}

            response = requests.post(url, json=payload)
            data = response.json()

            if 'error' in data:
                flash(f'Login failed: {data["error"]["message"]}', 'danger')
                return redirect(url_for('login'))

            user_id = data['localId']
            id_token = data['idToken']

            user_doc = db.collection('users').document(user_id).get()
            if not user_doc.exists:
                flash('User data not found.', 'danger')
                return redirect(url_for('login'))

            user_data = user_doc.to_dict()

            session['user_id'] = user_id
            session['email'] = email
            session['name'] = user_data.get('name')
            session['role'] = user_data.get('role')
            session['class_ids'] = user_data.get('class_ids', [])
            session['id_token'] = id_token

            flash(f'Welcome, {user_data.get("name")}!', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            flash(f'Login error: {str(e)}', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# =============================================================================
# DASHBOARD ROUTE
# =============================================================================

@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('role') == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    else:
        return redirect(url_for('student_dashboard'))

# =============================================================================
# TEACHER: CLASS MANAGEMENT ROUTES
# =============================================================================

@app.route('/teacher/classes')
@teacher_required
def teacher_classes():
    teacher_id = session['user_id']
    classes_ref = db.collection('classes').where('teacher_id', '==', teacher_id).stream()
    classes = []
    for doc in classes_ref:
        cls = doc.to_dict()
        cls['id'] = doc.id
        # Count enrolled students
        members_ref = db.collection('class_members').where('class_id', '==', doc.id).stream()
        cls['student_count'] = sum(1 for _ in members_ref)
        classes.append(cls)
    return render_template('teacher_classes.html', classes=classes)

@app.route('/teacher/classes/create', methods=['GET', 'POST'])
@teacher_required
def create_class():
    if request.method == 'POST':
        class_name = request.form.get('class_name', '').strip()
        description = request.form.get('description', '').strip()

        if not class_name:
            flash('Class name is required.', 'danger')
            return redirect(url_for('create_class'))

        join_code = generate_join_code()
        class_id = str(uuid.uuid4())

        db.collection('classes').document(class_id).set({
            'name': class_name,
            'description': description,
            'join_code': join_code,
            'teacher_id': session['user_id'],
            'teacher_name': session['name'],
            'created_at': datetime.now().isoformat()
        })

        flash(f'Class "{class_name}" created! Share Join Code: {join_code}', 'success')
        return redirect(url_for('teacher_classes'))

    return render_template('create_class.html')

@app.route('/teacher/classes/<class_id>/delete')
@teacher_required
def delete_class(class_id):
    cls_doc = db.collection('classes').document(class_id).get()
    if not cls_doc.exists or cls_doc.to_dict().get('teacher_id') != session['user_id']:
        flash('Class not found or access denied.', 'danger')
        return redirect(url_for('teacher_classes'))

    # Remove all members and update their class_ids lists
    members = db.collection('class_members').where('class_id', '==', class_id).stream()
    for m in members:
        sid = m.to_dict()['student_id']
        s_doc = db.collection('users').document(sid).get()
        if s_doc.exists:
            ids = s_doc.to_dict().get('class_ids', [])
            if class_id in ids:
                ids.remove(class_id)
            db.collection('users').document(sid).update({'class_ids': ids})
        m.reference.delete()

    db.collection('classes').document(class_id).delete()
    flash('Class deleted and students unenrolled.', 'info')
    return redirect(url_for('teacher_classes'))

@app.route('/teacher/classes/<class_id>/students')
@teacher_required
def class_students(class_id):
    cls_doc = db.collection('classes').document(class_id).get()
    if not cls_doc.exists or cls_doc.to_dict().get('teacher_id') != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('teacher_classes'))

    cls = cls_doc.to_dict()
    cls['id'] = class_id

    members_ref = db.collection('class_members').where('class_id', '==', class_id).stream()
    students = []
    for doc in members_ref:
        m = doc.to_dict()
        student_doc = db.collection('users').document(m['student_id']).get()
        if student_doc.exists:
            s = student_doc.to_dict()
            s['id'] = student_doc.id
            s['joined_at'] = m.get('joined_at', '')
            students.append(s)

    return render_template('class_students.html', cls=cls, students=students)

@app.route('/teacher/classes/<class_id>/remove/<student_id>', methods=['POST'])
@teacher_required
def remove_student(class_id, student_id):
    cls_doc = db.collection('classes').document(class_id).get()
    if not cls_doc.exists or cls_doc.to_dict().get('teacher_id') != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('teacher_classes'))

    members = db.collection('class_members')\
        .where('class_id', '==', class_id)\
        .where('student_id', '==', student_id)\
        .stream()
    for m in members:
        m.reference.delete()

    s_doc = db.collection('users').document(student_id).get()
    if s_doc.exists:
        ids = s_doc.to_dict().get('class_ids', [])
        if class_id in ids:
            ids.remove(class_id)
        db.collection('users').document(student_id).update({'class_ids': ids})

    flash('Student removed from class.', 'info')
    return redirect(url_for('class_students', class_id=class_id))

# =============================================================================
# TEACHER: EXAM ROUTES
# =============================================================================

@app.route('/teacher/dashboard')
@teacher_required
def teacher_dashboard():
    teacher_id = session['user_id']

    exams_ref = db.collection('exams').where('teacher_id', '==', teacher_id).stream()
    exams = []
    for doc in exams_ref:
        exam = doc.to_dict()
        exam['id'] = doc.id
        exams.append(exam)

    return render_template('teacher_dashboard.html', exams=exams)

@app.route('/teacher/create-exam', methods=['GET', 'POST'])
@teacher_required
def create_exam():
    teacher_id = session['user_id']
    # Get this teacher's classes for the dropdown
    classes_ref = db.collection('classes').where('teacher_id', '==', teacher_id).stream()
    classes = []
    for doc in classes_ref:
        c = doc.to_dict()
        c['id'] = doc.id
        classes.append(c)

    if request.method == 'POST':
        title = request.form.get('title')
        subject = request.form.get('subject')
        class_id = request.form.get('class_id', '').strip()
        try:
            duration = int(request.form.get('duration'))
            total_marks = int(request.form.get('total_marks'))
        except (ValueError, TypeError):
            flash('Invalid input for duration or total marks.', 'danger')
            return redirect(url_for('create_exam'))

        # Resolve class name from class_id
        target_class_name = 'All'
        target_class_id = None
        if class_id and class_id != 'all':
            cls_doc = db.collection('classes').document(class_id).get()
            if cls_doc.exists and cls_doc.to_dict().get('teacher_id') == teacher_id:
                target_class_name = cls_doc.to_dict().get('name')
                target_class_id = class_id
            else:
                flash('Invalid class selected.', 'danger')
                return redirect(url_for('create_exam'))

        opens_at_str = request.form.get('opens_at', '').strip() or None
        closes_at_str = request.form.get('closes_at', '').strip() or None

        exam_id = str(uuid.uuid4())
        db.collection('exams').document(exam_id).set({
            'title': title,
            'subject': subject,
            'target_class_id': target_class_id,
            'target_class_name': target_class_name,
            'duration_minutes': duration,
            'total_marks': total_marks,
            'teacher_id': teacher_id,
            'teacher_name': session['name'],
            'status': 'draft',
            'opens_at': opens_at_str,
            'closes_at': closes_at_str,
            'created_at': datetime.now().isoformat()
        })

        flash('Exam created! Now add questions.', 'success')
        return redirect(url_for('add_questions', exam_id=exam_id))

    return render_template('create_exam.html', classes=classes)

@app.route('/teacher/exam/<exam_id>/questions', methods=['GET', 'POST'])
@teacher_required
def add_questions(exam_id):
    exam_doc = db.collection('exams').document(exam_id).get()
    if not exam_doc.exists:
        flash('Exam not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    exam = exam_doc.to_dict()
    if exam.get('teacher_id') != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if request.method == 'POST':
        existing_questions = db.collection('questions').where('exam_id', '==', exam_id).stream()
        for q in existing_questions:
            q.reference.delete()

        questions_data = request.form.getlist('question[]')
        options_a = request.form.getlist('option_a[]')
        options_b = request.form.getlist('option_b[]')
        options_c = request.form.getlist('option_c[]')
        options_d = request.form.getlist('option_d[]')
        correct_options = request.form.getlist('correct[]')
        marks_list = request.form.getlist('marks[]')

        for i in range(len(questions_data)):
            q_id = str(uuid.uuid4())
            db.collection('questions').document(q_id).set({
                'exam_id': exam_id,
                'question_text': questions_data[i],
                'options': {
                    'A': options_a[i],
                    'B': options_b[i],
                    'C': options_c[i],
                    'D': options_d[i]
                },
                'correct_option': correct_options[i],
                'marks': int(marks_list[i])
            })

        flash('Questions saved successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))

    questions_ref = db.collection('questions').where('exam_id', '==', exam_id).stream()
    questions = []
    for doc in questions_ref:
        q = doc.to_dict()
        q['id'] = doc.id
        questions.append(q)

    return render_template('add_questions.html', exam_id=exam_id, exam=exam, questions=questions)

@app.route('/teacher/exam/<exam_id>/publish')
@teacher_required
def publish_exam(exam_id):
    exam_doc = db.collection('exams').document(exam_id).get()
    if not exam_doc.exists:
        flash('Exam not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    exam = exam_doc.to_dict()
    if exam.get('teacher_id') != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    db.collection('exams').document(exam_id).update({'status': 'published'})
    flash('Exam published successfully!', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/exam/<exam_id>/delete')
@teacher_required
def delete_exam(exam_id):
    exam_doc = db.collection('exams').document(exam_id).get()
    if not exam_doc.exists:
        flash('Exam not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    exam = exam_doc.to_dict()
    if exam.get('teacher_id') != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    for q in db.collection('questions').where('exam_id', '==', exam_id).stream():
        q.reference.delete()
    for r in db.collection('results').where('exam_id', '==', exam_id).stream():
        r.reference.delete()

    db.collection('exams').document(exam_id).delete()
    flash('Exam deleted.', 'info')
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher/exam/<exam_id>/results')
@teacher_required
def view_results(exam_id):
    exam_doc = db.collection('exams').document(exam_id).get()
    if not exam_doc.exists:
        flash('Exam not found.', 'danger')
        return redirect(url_for('teacher_dashboard'))
    exam = exam_doc.to_dict()
    if exam.get('teacher_id') != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('teacher_dashboard'))

    results_ref = db.collection('results').where('exam_id', '==', exam_id).stream()
    results = []
    for doc in results_ref:
        r = doc.to_dict()
        r['id'] = doc.id
        results.append(r)

    return render_template('view_results.html', exam=exam, results=results)

# =============================================================================
# STUDENT: JOIN CLASS ROUTE
# =============================================================================

@app.route('/student/join-class', methods=['GET', 'POST'])
@student_required
def join_class():
    if request.method == 'POST':
        join_code = request.form.get('join_code', '').strip().upper()

        classes_ref = db.collection('classes').where('join_code', '==', join_code).stream()
        cls_doc = next((doc for doc in classes_ref), None)

        if not cls_doc:
            flash('Invalid Join Code. Please check and try again.', 'danger')
            return redirect(url_for('join_class'))

        cls = cls_doc.to_dict()
        class_id = cls_doc.id
        student_id = session['user_id']

        # Check if already in this class
        already = db.collection('class_members')\
            .where('class_id', '==', class_id)\
            .where('student_id', '==', student_id)\
            .stream()
        if any(True for _ in already):
            flash('You are already enrolled in this class.', 'info')
            return redirect(url_for('student_dashboard'))

        # Enroll student in class_members
        db.collection('class_members').add({
            'class_id': class_id,
            'student_id': student_id,
            'student_name': session['name'],
            'joined_at': datetime.now().isoformat()
        })

        # Append class_id to user's class_ids list
        user_doc = db.collection('users').document(student_id).get()
        current_ids = user_doc.to_dict().get('class_ids', [])
        if class_id not in current_ids:
            current_ids.append(class_id)
        db.collection('users').document(student_id).update({'class_ids': current_ids})

        # Update session
        ids = session.get('class_ids', [])
        if class_id not in ids:
            ids.append(class_id)
        session['class_ids'] = ids

        flash(f'Successfully joined "{cls["name"]}"! You are now in {len(ids)} class(es).', 'success')
        return redirect(url_for('student_dashboard'))

    return render_template('join_class.html')

@app.route('/student/leave-class/<class_id>')
@student_required
def leave_class(class_id):
    student_id = session['user_id']
    class_ids = list(session.get('class_ids', []))

    if class_id not in class_ids:
        flash('You are not enrolled in this class.', 'info')
        return redirect(url_for('student_dashboard'))

    # Remove membership record
    members = db.collection('class_members')\
        .where('class_id', '==', class_id)\
        .where('student_id', '==', student_id)\
        .stream()
    for m in members:
        m.reference.delete()

    # Remove from user's class_ids list
    class_ids.remove(class_id)
    db.collection('users').document(student_id).update({'class_ids': class_ids})
    session['class_ids'] = class_ids

    flash('You have left the class.', 'info')
    return redirect(url_for('student_dashboard'))

# =============================================================================
# STUDENT: EXAM ROUTES
# =============================================================================

@app.route('/student/dashboard')
@student_required
def student_dashboard():
    student_id = session['user_id']
    class_ids = session.get('class_ids', [])
    now_str = datetime.now().isoformat()

    # Fetch full class details for display
    my_classes = []
    for cid in class_ids:
        cls_doc = db.collection('classes').document(cid).get()
        if cls_doc.exists:
            c = cls_doc.to_dict()
            c['id'] = cid
            my_classes.append(c)

    attempted_exam_ids = set()
    past_results = []
    for doc in db.collection('results').where('student_id', '==', student_id).stream():
        r = doc.to_dict()
        r['id'] = doc.id
        past_results.append(r)
        attempted_exam_ids.add(r['exam_id'])

    available_exams = []
    if class_ids:
        for doc in db.collection('exams').where('status', '==', 'published').stream():
            exam = doc.to_dict()
            exam['id'] = doc.id
            target_id = exam.get('target_class_id')

            # Class gate: exam for specific class must match one of student's classes
            if target_id is not None and target_id not in class_ids:
                continue
            if exam['id'] in attempted_exam_ids:
                continue

            # Schedule status
            opens_at = exam.get('opens_at')
            closes_at = exam.get('closes_at')
            if opens_at and now_str < opens_at:
                exam['schedule_status'] = 'upcoming'
            elif closes_at and now_str > closes_at:
                exam['schedule_status'] = 'closed'
            else:
                exam['schedule_status'] = 'open'

            available_exams.append(exam)

    return render_template('student_dashboard.html',
                           available_exams=available_exams,
                           past_results=past_results,
                           my_classes=my_classes,
                           class_ids=class_ids)

@app.route('/student/exam/<exam_id>')
@student_required
def take_exam(exam_id):
    exam_doc = db.collection('exams').document(exam_id).get()
    if not exam_doc.exists:
        flash('Exam not found.', 'danger')
        return redirect(url_for('student_dashboard'))

    exam = exam_doc.to_dict()
    if exam.get('status') != 'published':
        flash('This exam is not available.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Server-side class access check
    target_class_id = exam.get('target_class_id')
    student_class_ids = session.get('class_ids', [])
    if not student_class_ids and target_class_id:
        flash('You must join a class to take this exam.', 'warning')
        return redirect(url_for('join_class'))
    if target_class_id and target_class_id not in student_class_ids:
        flash('Access denied. This exam is not assigned to your class.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Server-side schedule check
    now_str = datetime.now().isoformat()
    opens_at = exam.get('opens_at')
    closes_at = exam.get('closes_at')
    if opens_at and now_str < opens_at:
        flash(f'This exam has not opened yet. Opens at {opens_at[:16].replace("T", " ")}.', 'warning')
        return redirect(url_for('student_dashboard'))
    if closes_at and now_str > closes_at:
        flash(f'This exam has closed. It closed at {closes_at[:16].replace("T", " ")}.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Check if already attempted
    results_ref = db.collection('results')\
        .where('student_id', '==', session['user_id'])\
        .where('exam_id', '==', exam_id)\
        .stream()
    if any(True for _ in results_ref):
        flash('You have already attempted this exam.', 'warning')
        return redirect(url_for('student_dashboard'))

    questions_ref = db.collection('questions').where('exam_id', '==', exam_id).stream()
    questions = []
    for doc in questions_ref:
        q = doc.to_dict()
        q['id'] = doc.id
        questions.append(q)

    session_key = f"start_time_{exam_id}"
    if session_key not in session:
        session[session_key] = datetime.now().timestamp()

    elapsed = int(datetime.now().timestamp() - session[session_key])
    remaining_seconds = max(0, (exam.get('duration_minutes', 0) * 60) - elapsed)

    return render_template('take_exam.html', exam=exam, questions=questions,
                           exam_id=exam_id, now=session[session_key],
                           remaining_seconds=remaining_seconds)

@app.route('/student/exam/<exam_id>/submit', methods=['POST'])
@student_required
def submit_exam(exam_id):
    student_id = session['user_id']

    session_key = f"start_time_{exam_id}"
    start_time = session.get(session_key) or float(request.form.get('start_time', datetime.now().timestamp()))
    session.pop(session_key, None)

    time_taken = int((datetime.now().timestamp() - start_time))

    questions_ref = db.collection('questions').where('exam_id', '==', exam_id).stream()
    questions = {doc.id: doc.to_dict() for doc in questions_ref}

    score = 0
    total_marks = 0
    answers = {}

    for q_id, q_data in questions.items():
        total_marks += q_data['marks']
        student_answer = request.form.get(f'question_{q_id}')
        answers[q_id] = student_answer or 'Not Answered'
        if student_answer == q_data['correct_option']:
            score += q_data['marks']

    exam_doc = db.collection('exams').document(exam_id).get()
    exam_title = exam_doc.to_dict().get('title') if exam_doc.exists else 'Exam'

    # Proctoring violation counts submitted via hidden form inputs
    tab_switches     = int(request.form.get('tab_switches', 0))
    fullscreen_exits = int(request.form.get('fullscreen_exits', 0))
    copy_attempts    = int(request.form.get('copy_attempts', 0))
    total_violations = tab_switches + fullscreen_exits + copy_attempts

    result_id = str(uuid.uuid4())
    db.collection('results').document(result_id).set({
        'student_id': student_id,
        'student_name': session['name'],
        'exam_id': exam_id,
        'exam_title': exam_title,
        'score': score,
        'total_marks': total_marks,
        'answers': answers,
        'time_taken_seconds': time_taken,
        'submitted_at': datetime.now().isoformat(),
        'proctoring': {
            'tab_switches': tab_switches,
            'fullscreen_exits': fullscreen_exits,
            'copy_attempts': copy_attempts,
            'total_violations': total_violations
        }
    })

    return redirect(url_for('view_result', result_id=result_id))

@app.route('/student/result/<result_id>')
@student_required
def view_result(result_id):
    result_doc = db.collection('results').document(result_id).get()
    if not result_doc.exists:
        flash('Result not found.', 'danger')
        return redirect(url_for('student_dashboard'))
    result = result_doc.to_dict()
    if result.get('student_id') != session['user_id']:
        flash('Access denied.', 'danger')
        return redirect(url_for('student_dashboard'))

    exam_doc = db.collection('exams').document(result['exam_id']).get()
    if not exam_doc.exists:
        flash('Exam not found.', 'danger')
        return redirect(url_for('student_dashboard'))
    exam = exam_doc.to_dict()

    questions_ref = db.collection('questions').where('exam_id', '==', result['exam_id']).stream()
    questions = []
    for doc in questions_ref:
        q = doc.to_dict()
        q['id'] = doc.id
        q['student_answer'] = result['answers'].get(doc.id, 'Not Answered')
        questions.append(q)

    percentage = (result['score'] / result['total_marks'] * 100) if result['total_marks'] > 0 else 0

    return render_template('result.html',
                           result=result,
                           exam=exam,
                           questions=questions,
                           percentage=percentage)

# =============================================================================
# RUN APP
# =============================================================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
