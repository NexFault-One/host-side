from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import uuid
import hashlib

# ---------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./nexfault.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- NEW: User Table ---
class DBUser(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)

# --- UPDATED: Profile Table (Now linked to user_id) ---
class DBProfile(Base):
    __tablename__ = "profiles"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id")) # Ties profile to a user
    profile_name = Column(String, index=True)
    description = Column(String)
    injection_type = Column(String)
    transport = Column(String)
    payload = Column(String)
    injection_params = Column(String)
    duration = Column(String)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper to hash passwords securely
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

app = FastAPI(title="NexFault API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

# ---------------------------------------------------------
# PYDANTIC MODELS (Data Validation)
# ---------------------------------------------------------
class UserCreate(BaseModel):
    firstName: str
    lastName: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: str
    firstName: str
    lastName: str
    email: str

class ProfileBase(BaseModel):
    userId: str # Added so the backend knows who owns the profile
    profileName: str
    description: str = ""
    injectionType: str
    transport: str
    payload: str = ""
    injectionParams: str = ""
    duration: str

class ProfileResponse(ProfileBase):
    id: str
    class Config:
        from_attributes = True

# ---------------------------------------------------------
# API ENDPOINTS
# ---------------------------------------------------------

# --- AUTH ENDPOINTS ---
@app.post("/users/register", response_model=UserResponse)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    # Check if email already exists
    if db.query(DBUser).filter(DBUser.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    db_user = DBUser(
        id=str(uuid.uuid4()),
        first_name=user.firstName,
        last_name=user.lastName,
        email=user.email,
        password_hash=hash_password(user.password)
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return UserResponse(id=db_user.id, firstName=db_user.first_name, lastName=db_user.last_name, email=db_user.email)

@app.post("/users/login", response_model=UserResponse)
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == user.email).first()
    
    # Check if user exists and password matches
    if not db_user or db_user.password_hash != hash_password(user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    return UserResponse(id=db_user.id, firstName=db_user.first_name, lastName=db_user.last_name, email=db_user.email)

# --- PROFILE ENDPOINTS ---
@app.post("/profiles", response_model=ProfileResponse, status_code=201)
def create_profile(profile: ProfileBase, db: Session = Depends(get_db)):
    db_profile = DBProfile(
        id=str(uuid.uuid4()),
        user_id=profile.userId,
        profile_name=profile.profileName,
        description=profile.description,
        injection_type=profile.injectionType,
        transport=profile.transport,
        payload=profile.payload,
        injection_params=profile.injectionParams,
        duration=profile.duration
    )
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return ProfileResponse(id=db_profile.id, **profile.dict())

@app.get("/profiles", response_model=list[ProfileResponse])
def get_profiles(user_id: str, db: Session = Depends(get_db)):
    # ONLY return profiles that belong to the logged-in user!
    profiles = db.query(DBProfile).filter(DBProfile.user_id == user_id).all()
    return [
        ProfileResponse(
            id=p.id, userId=p.user_id, profileName=p.profile_name, description=p.description,
            injectionType=p.injection_type, transport=p.transport, payload=p.payload,
            injectionParams=p.injection_params, duration=p.duration
        ) for p in profiles
    ]

@app.put("/profiles/{profile_id}", response_model=ProfileResponse)
def update_profile(profile_id: str, profile: ProfileBase, db: Session = Depends(get_db)):
    db_profile = db.query(DBProfile).filter(DBProfile.id == profile_id).first()
    if not db_profile: raise HTTPException(status_code=404, detail="Profile not found")
    
    db_profile.profile_name = profile.profileName
    db_profile.description = profile.description
    db_profile.injection_type = profile.injectionType
    db_profile.transport = profile.transport
    db_profile.payload = profile.payload
    db_profile.injection_params = profile.injectionParams
    db_profile.duration = profile.duration

    db.commit()
    return ProfileResponse(id=db_profile.id, **profile.dict())

@app.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    db_profile = db.query(DBProfile).filter(DBProfile.id == profile_id).first()
    if not db_profile: raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(db_profile)
    db.commit()
    return None