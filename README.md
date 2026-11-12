# Online Examination System with Rubric Auditing Mechanism

**Complete Phase 1, Phase 2 & Phase 3 Integrated Application** — A role-isolated SaaS academic examination, rubric evaluation, result management, and NLP-assisted rubric auditing platform built with **Python Flask**, **Cloud Firestore**, **Firebase Authentication**, **scikit-learn**, and modular **HTML5 / CSS3 / ES6 JavaScript**.

---

## Key Capabilities

### Phase 1: Authentication, Exam Authoring & Delivery
- **Real Firebase Authentication + Server-Verified RBAC**: `HttpOnly` Firebase session cookies (`rubriassess_fb_session`) + independent Flask CSRF session (`rubriassess_csrf_session`), student-locked self-registration, and Admin/Examiner provisioning.
- **Exam Lifecycle & Delivery**: Exam scheduling, Question & Rubric Bank, Pre-Exam Instructions, synchronized exam timer, question navigator palette, 15s autosave, and auto-submit on expiry.

### Phase 2: Examination Processing, Rubric Evaluation & Result Management
- **MCQ Automated Evaluation**: Instant deterministic scoring on submission with configurable negative marking (`negative_marking_enabled`, `negative_mark_fraction`) and duplicate-evaluation protection.
- **Descriptive Rubric Evaluation Studio (`/examiner/evaluations/<submission_id>`)**: Transparent preliminary phrase/concept matching (`EvaluationService`), criterion-level mark editing (`0..max_marks`), examiner feedback, and `decision_history`.
- **Result Management & Publication (`/examiner/exams/<exam_id>/results`, `/student/results`, `/student/results/<result_id>`)**: Deterministic `results/{exam_id}__{student_uid}` records, configurable `grade_rules`, Pass/Fail calculation, and published student result reports.

### Phase 3: Intelligent Rubric Auditing & Alternative Phrase Detection
- **Hybrid NLP Phrase Alignment (`CalibratedHybridNlpEngine`)**: Uses clause segmentation, morphological suffix canonicalization, curated conceptual-anchor projection, negation asymmetry filtering, scikit-learn word & character n-gram TF-IDF cosine similarity, and context-grounding gating to surface potential alternative wording without false positives on unrelated surface matches.
- **Rubric Audit Report Dashboard (`/examiner/audit`)**: Filterable by status (`pending`, `approved`, `rejected`), examination, and rubric criterion; displays confidence scores, rationale, expected vs detected phrase comparisons, and affected student excerpts.
- **Examiner Approval & Re-evaluation Workflow**:
  - **Approve Suggestion**: Archives previous rubric snapshot in `rubric_versions`, appends approved alternative phrase to the rubric (`version + 1`), preserves historical evaluation snapshots (`grading.evaluation_history`), re-evaluates affected submissions, recalculates results when marks legitimately change, and notifies affected students (`notifications`).
  - **Reject Suggestion**: Preserves original rubric unchanged and records optional examiner rejection rationale without triggering re-evaluation.

---

## Project Structure

```text
SOBI/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── run.py
├── wsgi.py
├── scripts/
│   └── create_admin.py
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── exceptions.py
│   ├── extensions/
│   │   ├── __init__.py
│   │   └── firebase.py
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── csrf.py
│   │   └── error_handlers.py
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── admin_validators.py
│   │   ├── audit_validators.py
│   │   ├── auth_validators.py
│   │   ├── common.py
│   │   ├── evaluation_validators.py
│   │   ├── exam_validators.py
│   │   ├── question_validators.py
│   │   └── submission_validators.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── audit_repo.py
│   │   ├── base.py
│   │   ├── exam_repo.py
│   │   ├── question_repo.py
│   │   ├── result_repo.py
│   │   ├── rubric_audit_repo.py
│   │   ├── rubric_repo.py
│   │   ├── submission_repo.py
│   │   └── user_repo.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── admin_service.py
│   │   ├── audit_service.py
│   │   ├── auth_service.py
│   │   ├── evaluation_service.py
│   │   ├── exam_service.py
│   │   ├── nlp_engine.py
│   │   ├── question_service.py
│   │   ├── result_service.py
│   │   ├── rubric_audit_service.py
│   │   ├── submission_service.py
│   │   └── time_utils.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── admin_api.py
│   │   ├── auth_api.py
│   │   ├── examiner_api.py
│   │   ├── helpers.py
│   │   ├── pages.py
│   │   └── student_api.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── base_app.html
│   │   ├── base_exam.html
│   │   ├── auth/login.html
│   │   ├── errors/{403,404,500}.html
│   │   ├── student/{dashboard,exam_instructions,exam_attempt,submission_confirmation,history,results,result_detail}.html
│   │   ├── examiner/{dashboard,exam_editor,question_bank,exam_results,evaluate_submission,rubric_audit}.html
│   │   └── admin/dashboard.html
│   └── static/
│       ├── css/{tokens,base,components,layouts,pages}.css
│       └── js/
│           ├── core/{apiClient,firebaseClient,modal,toast,ui,validators}.js
│           └── pages/{adminDashboard,auth,evaluateSubmission,examAttempt,examEditor,examHistory,examResults,examinerDashboard,examInstructions,questionBank,rubricAudit,studentDashboard,studentResultDetail,studentResults,submissionConfirmation}.js
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── fakes.py
    ├── test_admin_flows.py
    ├── test_auth_and_rbac.py
    ├── test_examiner_flows.py
    ├── test_phase2_evaluation_and_results.py
    ├── test_phase3_rubric_auditing.py
    └── test_student_exam_flow.py
```

---

## Firebase Configuration

1. **Create a Firebase Project** in the [Firebase Console](https://console.firebase.google.com/).
2. **Enable Authentication**:
   - Navigate to **Build → Authentication → Sign-in method** and enable **Email/Password**.
3. **Create Cloud Firestore Database**:
   - Navigate to **Build → Firestore Database → Create database**.
   - Recommended Firestore Rules (all production writes in Phase 1 go through the Flask Admin SDK, so direct client Firestore access should be locked down):
     ```js
     rules_version = '2';
     service cloud.firestore {
       match /databases/{database}/documents {
         match /{document=**} {
           allow read, write: if false;
         }
       }
     }
     ```
4. **Download Service Account Credentials (Server-Only)**:
   - Go to **Project Settings → Service Accounts → Generate new private key**.
   - Save the JSON file to `./secrets/serviceAccountKey.json` (git-ignored). **Never place this file inside `app/static/` or expose it to frontend code.**
5. **Copy Web App Public Keys**:
   - Go to **Project Settings → General → Your apps → Web app (`</>`)** and copy `apiKey`, `authDomain`, `projectId`, `storageBucket`, `messagingSenderId`, and `appId`.
6. **Configure `.env`**:
   ```bash
   cp .env.example .env
   ```
   Fill in `SECRET_KEY`, `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_PATH`, and all `FIREBASE_WEB_*` variables.
7. **Provision the First Admin Account**:
   ```bash
   python scripts/create_admin.py --email admin@university.edu --name "System Administrator" --role admin --institution-id ADM-001
   ```
   Once signed in at `/login`, use the **Admin Control Center** to create Examiner and Student accounts.

---

## Running the Application

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Start Flask development server**:
   ```bash
   python run.py
   ```
   Open `http://127.0.0.1:5000` in your browser.
3. **Production WSGI**:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
   ```

---

## Running Tests

```bash
python -m pytest -v
```

#   o n l i n e - e x a m - r u b r i c - a u d i t i n g  
 