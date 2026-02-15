from sqlalchemy import Column, Integer, BigInteger, String, Text, TIMESTAMP, Boolean
from sqlalchemy.sql import func
from . import Base


class HRUser(Base):
    __tablename__ = "hr_users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    phone = Column(String(20))
    employee_id = Column(String(50))
    full_name = Column(String(255))
    first_name = Column(String(100))
    last_name = Column(String(100))
    department = Column(String(200))
    position = Column(String(200))
    start_date = Column(String(50))
    email = Column(String(255))

    access_level = Column(String(20), server_default='employee')
    verification_method = Column(String(50), server_default='sed_api')
    manually_added_by = Column(Integer)
    notes = Column(Text)

    last_sed_sync = Column(TIMESTAMP)
    sed_sync_status = Column(String(50))
    is_active = Column(Boolean, server_default='true')

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class HRWhitelist(Base):
    __tablename__ = "hr_whitelist"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    full_name = Column(String(255), nullable=False)
    access_level = Column(String(20), server_default='contractor')
    reason = Column(Text)
    added_by = Column(String(255))
    added_at = Column(TIMESTAMP, server_default=func.now())
    is_active = Column(Boolean, server_default='true')


class VerificationLog(Base):
    __tablename__ = "verification_log"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, nullable=False)
    phone = Column(String(20))
    employee_id = Column(String(50))
    verification_type = Column(String(50))
    status = Column(String(50))
    created_at = Column(TIMESTAMP, server_default=func.now())
