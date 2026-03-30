from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Depends, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import shutil
import os
import uuid
import uvicorn

from app.database import init_db, SessionLocal, Candidate, HRUser, JobRole
from app.worker import process_resume_task
from app.schemas import MatchRequest, MatchResult, BatchMatchRequest, HRSup, HRLogin, JobCreate, JobResponse
from app.agents.matcher import match_candidate_to_job
from typing import List

app = FastAPI(
    title="Talent Intelligence API",
    description="Multi-Agent System for Intelligent Resume Parsing, Match, and API",
    version="1.0.0"
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
def on_startup():
    init_db()

@app.post("/api/v1/parse", tags=["Resume Parsing"])
async def upload_resume(file: UploadFile = File(...), job_id: int = Form(None)):
    """
    Upload a resume (PDF/DOCX) for asynchronous processing.
    """
    # Ensure the data directory exists
    os.makedirs("/app/data", exist_ok=True)
    file_ext = os.path.splitext(file.filename)[1]
    
    # Save file to a shared volume path
    temp_filename = f"/app/data/{uuid.uuid4()}{file_ext}"
    
    with open(temp_filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Send to Celery worker queue
    task = process_resume_task.delay(temp_filename, file.filename, job_id)
    
    return {"task_id": task.id, "message": "Resume parsing task enqueued."}

@app.get("/api/v1/parse/status/{task_id}", tags=["Resume Parsing"])
def get_parse_status(task_id: str):
    """
    Poll the status of a background resume parsing async job.
    """
    from app.worker import celery
    task = celery.AsyncResult(task_id)
    if task.state == "SUCCESS":
        return {"status": task.state, "result": task.result}
    return {"status": task.state}

@app.get("/api/v1/candidates/{candidate_id}/skills", tags=["Candidates"])
def get_candidate_skills(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    return {
        "candidate_id": candidate_id, 
        "skills": candidate.resume_data.get("normalized_skills", candidate.resume_data.get("skills", []))
    }

@app.get("/api/v1/candidates/{candidate_id}", tags=["Candidates"])
def get_candidate_details(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    return {
        "candidate_id": candidate.id,
        "name": candidate.name,
        "resume_data": candidate.resume_data
    }

@app.get("/api/v1/candidates/{candidate_id}/resume", tags=["Candidates"])
def download_candidate_resume(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    file_path = candidate.resume_data.get("file_path")
    filename = candidate.resume_data.get("filename", "resume.pdf")
    
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Resume file not found on disk")
        
    return FileResponse(path=file_path, filename=filename, media_type='application/octet-stream')

@app.post("/api/v1/match", tags=["Job Matching"])
def match_candidate(request: MatchRequest, db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == request.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    result = match_candidate_to_job(candidate, request)
    return result

@app.post("/api/v1/match/batch", tags=["Job Matching"])
def match_batch_candidates(request: BatchMatchRequest, db: Session = Depends(get_db)):
    candidates = db.query(Candidate).filter(Candidate.id.in_(request.candidate_ids)).all()
    results = []
    for candidate in candidates:
        res = match_candidate_to_job(candidate, request)
        results.append(res)
    
    results.sort(key=lambda x: x.score, reverse=True)
    return {"matches": results}

# --- HR Auth and Jobs ---
@app.post("/api/v1/auth/signup", tags=["Authentication"])
def hr_signup(hr: HRSup, db: Session = Depends(get_db)):
    existing = db.query(HRUser).filter(HRUser.email == hr.email).first()
    if existing: raise HTTPException(status_code=400, detail="Email already registered")
    
    new_hr = HRUser(name=hr.name, email=hr.email, password=hr.password, company_name=hr.company_name)
    db.add(new_hr)
    db.commit()
    db.refresh(new_hr)
    return {"id": new_hr.id, "email": new_hr.email, "message": "Signed up successfully."}

@app.post("/api/v1/auth/login", tags=["Authentication"])
def hr_login(hr: HRLogin, db: Session = Depends(get_db)):
    user = db.query(HRUser).filter(HRUser.email == hr.email, HRUser.password == hr.password).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"id": user.id, "name": user.name, "company_name": user.company_name}

@app.post("/api/v1/jobs", response_model=JobResponse, tags=["Jobs"])
def create_job(job: JobCreate, db: Session = Depends(get_db)):
    new_job = JobRole(**job.dict())
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job

@app.get("/api/v1/jobs/hr/{hr_id}", tags=["Jobs"])
def get_hr_jobs(hr_id: int, db: Session = Depends(get_db)):
    return db.query(JobRole).filter(JobRole.hr_id == hr_id).all()

@app.get("/api/v1/jobs/{job_id}", tags=["Jobs"])
def get_job(job_id: int, db: Session = Depends(get_db)):
    return db.query(JobRole).filter(JobRole.id == job_id).first()

@app.get("/api/v1/jobs/{job_id}/candidates", tags=["Jobs"])
def get_job_candidates(job_id: int, db: Session = Depends(get_db)):
    candidates = db.query(Candidate).filter(Candidate.job_id == job_id).all()
    return [{"id": c.id, "name": c.name} for c in candidates]

# --- Static File Serving ---
# Using 'static' instead of 'app/static' because of the Docker WORKDIR flattening
static_path = "static" if os.path.exists("static") else "app/static"
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

# --- Startup Block for Railway ---
if __name__ == "__main__":
    # Get port from environment variable (Railway default) or fallback to 8000
    port = int(os.environ.get("PORT", 8000))
    # Must listen on 0.0.0.0 for external traffic
    uvicorn.run(app, host="0.0.0.0", port=port)
