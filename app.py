import firebase_admin
from firebase_admin import credentials, firestore, auth as admin_auth
from flask import Flask, render_template, request, redirect, url_for, session, flash
import requests
import json
import os
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
            
            # Store user data in Firestore
            db.collection('users').document(user.uid).set({
                'name': name,
                'email': email,
                'role': role,
                'created_at': datetime.now().isoformat()
            })
            
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
            # Sign in with Firebase Auth REST API
            api_key = app.config['FIREBASE_WEB_API_KEY']
            url = f"{FIREBASE_AUTH_URL}:signInWithPassword?key={api_key}"
            
            payload = {
                "email": email,
                "password": password,
                "returnSecureToken": True
            }
            
            response = requests.post(url, json=payload)
            data = response.json()
            
            if 'error' in data:
                flash(f'Login failed: {data["error"]["message"]}', 'danger')
                return redirect(url_for('login'))
            
            user_id = data['localId']
            id_token = data['idToken']
            
            # Get user role from Firestore
            user_doc = db.collection('users').document(user_id).get()
            if not user_doc.exists:
                flash('User data not found.', 'danger')
                return redirect(url_for('login'))
            
            user_data = user_doc.to_dict()
            
            # Set session
            session['user_id'] = user_id
            session['email'] = email
            session['name'] = user_data.get('name')
            session['role'] = user_data.get('role')
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
# TEACHER ROUTES
# =============================================================================

@app.route('/teacher/dashboard')
@teacher_required
def teacher_dashboard():
    teacher_id = session['user_id']
    
    # Get all exams created by this teacher
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
    if request.method == 'POST':
        title = request.form.get('title')
        subject = request.form.get('subject')
        try:
            duration = int(request.form.get('duration'))
            total_marks = int(request.form.get('total_marks'))
        except (ValueError, TypeError):
            flash('Invalid input for duration or total marks.', 'danger')
            return redirect(url_for('create_exam'))
        
        exam_id = str(uuid.uuid4())
        
        db.collection('exams').document(exam_id).set({
            'title': title,
            'subject': subject,
            'duration_minutes': duration,
            'total_marks': total_marks,
            'teacher_id': session['user_id'],
            'teacher_name': session['name'],
            'status': 'draft',
            'created_at': datetime.now().isoformat()
        })
        
        flash('Exam created! Now add questions.', 'success')
        return redirect(url_for('add_questions', exam_id=exam_id))
    
    return render_template('create_exam.html')

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
        # Clear existing questions for this exam first to prevent duplicates
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
    
    # Load existing questions to display in form
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
        
    db.collection('exams').document(exam_id).update({
        'status': 'published'
    })
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
        
    # Delete questions first
    questions_ref = db.collection('questions').where('exam_id', '==', exam_id).stream()
    for q in questions_ref:
        q.reference.delete()
        
    # Delete results first
    results_ref = db.collection('results').where('exam_id', '==', exam_id).stream()
    for r in results_ref:
        r.reference.delete()
    
    # Delete exam
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
# STUDENT ROUTES
# =============================================================================

@app.route('/student/dashboard')
@student_required
def student_dashboard():
    student_id = session['user_id']
    
    # Get all published exams
    exams_ref = db.collection('exams').where('status', '==', 'published').stream()
    available_exams = []
    attempted_exam_ids = set()
    
    # Get attempted exams
    results_ref = db.collection('results').where('student_id', '==', student_id).stream()
    past_results = []
    for doc in results_ref:
        r = doc.to_dict()
        r['id'] = doc.id
        past_results.append(r)
        attempted_exam_ids.add(r['exam_id'])
    
    for doc in exams_ref:
        exam = doc.to_dict()
        exam['id'] = doc.id
        if exam['id'] not in attempted_exam_ids:
            available_exams.append(exam)
    
    return render_template('student_dashboard.html', 
                         available_exams=available_exams,
                         past_results=past_results)

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
    
    # Check if already attempted
    results_ref = db.collection('results')\
        .where('student_id', '==', session['user_id'])\
        .where('exam_id', '==', exam_id)\
        .stream()
    
    if any(True for _ in results_ref):
        flash('You have already attempted this exam.', 'warning')
        return redirect(url_for('student_dashboard'))
    
    # Get questions
    questions_ref = db.collection('questions').where('exam_id', '==', exam_id).stream()
    questions = []
    for doc in questions_ref:
        q = doc.to_dict()
        q['id'] = doc.id
        questions.append(q)
        
    # Prevent timer cheating/resets by saving start time to session
    session_key = f"start_time_{exam_id}"
    if session_key not in session:
        session[session_key] = datetime.now().timestamp()
        
    elapsed = int(datetime.now().timestamp() - session[session_key])
    remaining_seconds = max(0, (exam.get('duration_minutes', 0) * 60) - elapsed)
    
    return render_template('take_exam.html', exam=exam, questions=questions, exam_id=exam_id, now=session[session_key], remaining_seconds=remaining_seconds)

@app.route('/student/exam/<exam_id>/submit', methods=['POST'])
@student_required
def submit_exam(exam_id):
    student_id = session['user_id']
    
    session_key = f"start_time_{exam_id}"
    start_time = session.get(session_key) or float(request.form.get('start_time', datetime.now().timestamp()))
    session.pop(session_key, None) # clear it after submission
    
    time_taken = int((datetime.now().timestamp() - start_time))
    
    # Get all questions for this exam
    questions_ref = db.collection('questions').where('exam_id', '==', exam_id).stream()
    questions = {doc.id: doc.to_dict() for doc in questions_ref}
    
    # Calculate score
    score = 0
    total_marks = 0
    answers = {}
    
    for q_id, q_data in questions.items():
        total_marks += q_data['marks']
        student_answer = request.form.get(f'question_{q_id}')
        answers[q_id] = student_answer or 'Not Answered'
        
        if student_answer == q_data['correct_option']:
            score += q_data['marks']
            
    # Retrieve exam title to store in results
    exam_doc = db.collection('exams').document(exam_id).get()
    exam_title = exam_doc.to_dict().get('title') if exam_doc.exists else 'Exam'
    
    # Save result
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
        'submitted_at': datetime.now().isoformat()
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
    
    # Get questions for review
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
