from sqlalchemy import Column, Integer, BigInteger, String, Text, TIMESTAMP, Boolean, Float, ForeignKey
from sqlalchemy.sql import func
from . import Base


class HuntVacancy(Base):
    __tablename__ = "hunt_vacancies"

    id = Column(Integer, primary_key=True, index=True)
    tg_message_id = Column(BigInteger)
    tg_thread_id = Column(BigInteger)
    tg_chat_id = Column(BigInteger)
    raw_text = Column(Text, nullable=False)
    position = Column(String(200))
    city = Column(String(100))
    requirements = Column(Text)
    salary_max = Column(Integer)
    status = Column(String(50), default='searching')
    created_at = Column(TIMESTAMP, server_default=func.now())


class HuntCandidate(Base):
    __tablename__ = "hunt_candidates"

    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("hunt_vacancies.id"))
    source = Column(String(50))
    full_name = Column(String(200))
    age = Column(Integer)
    city = Column(String(100))
    experience_years = Column(Float)
    current_role = Column(String(200))
    skills = Column(Text)
    salary_expectation = Column(Integer)
    contact = Column(String(200))
    profile_url = Column(Text)
    raw_text = Column(Text)
    ai_score = Column(Integer)
    ai_summary = Column(Text)
    hr_decision = Column(String(20), default='pending')
    telegram_message_id = Column(BigInteger)
    created_at = Column(TIMESTAMP, server_default=func.now())


class HuntSource(Base):
    __tablename__ = "hunt_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    tg_channel = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
