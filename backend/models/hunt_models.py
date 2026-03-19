from sqlalchemy import Column, Integer, BigInteger, String, Text, TIMESTAMP, Boolean, Float, ForeignKey, DateTime
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
    hired_at = Column(DateTime)
    candidate_date = Column(TIMESTAMP)
    is_fallback = Column(Boolean, default=False)
    fallback_round = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())


class HuntSource(Base):
    __tablename__ = "hunt_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    tg_channel = Column(String(100), unique=True)
    is_active = Column(Boolean, default=True)
    channel_type = Column(String(20), default='scan')
    created_at = Column(TIMESTAMP, server_default=func.now())


class HuntPosting(Base):
    __tablename__ = "hunt_postings"

    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("hunt_vacancies.id"))
    channel = Column(String(100))
    status = Column(String(20))
    error_message = Column(Text)
    posted_at = Column(TIMESTAMP, server_default=func.now())


class HuntSalaryData(Base):
    __tablename__ = "hunt_salary_data"

    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("hunt_vacancies.id"))
    source = Column(String(50))
    data_type = Column(String(20))
    position = Column(String(200))
    city = Column(String(100))
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_median = Column(Integer)
    currency = Column(String(10), default='UAH')
    skills = Column(Text)
    source_url = Column(Text)
    salary_min_uah = Column(Integer)
    salary_max_uah = Column(Integer)
    salary_median_uah = Column(Integer)
    salary_min_usd = Column(Integer)
    salary_max_usd = Column(Integer)
    salary_median_usd = Column(Integer)
    currency_detected = Column(String(10))
    usd_rate_at_collection = Column(Float)
    sample_count = Column(Integer, default=0)
    collected_at = Column(TIMESTAMP, server_default=func.now())
