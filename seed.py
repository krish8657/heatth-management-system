"""Seed 300 doctors and their specialties into MongoDB.

Run from the project directory:
    python seed.py

All seeded doctors use:
    Password: Doctor@123
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://tandelkrish628_db_user:6xatdUbleFqmCEPo@custer.7vkcxdn.mongodb.net/")
DATABASE_NAME = "health_db"
SEEDED_EMAIL_PREFIX = "doctor"
SEEDED_EMAIL_DOMAIN = "@smarthealth.example"
DOCTOR_PASSWORD = "Doctor@123"

SPECIALTIES = [
    {"name": "Cardiology", "icon": "heart"},
    {"name": "Dermatology", "icon": "skin"},
    {"name": "General Physician", "icon": "doctor"},
    {"name": "Gynecology", "icon": "women"},
    {"name": "Neurology", "icon": "brain"},
    {"name": "Orthopedics", "icon": "bone"},
    {"name": "Pediatrics", "icon": "child"},
    {"name": "Psychiatry", "icon": "mental-health"},
    {"name": "Ophthalmology", "icon": "eye"},
    {"name": "ENT", "icon": "ear"},
    {"name": "Dentistry", "icon": "tooth"},
    {"name": "Pulmonology", "icon": "lungs"},
]

FIRST_NAMES = [
    "Aarav", "Aditi", "Akash", "Ananya", "Arjun",
    "Bhavna", "Dev", "Diya", "Ishaan", "Kavya",
    "Karan", "Kriti", "Manav", "Meera", "Neha",
    "Nikhil", "Pooja", "Rahul", "Riya", "Rohan",
    "Sahil", "Sneha", "Tanvi", "Varun", "Vivek",
]

LAST_NAMES = [
    "Sharma", "Patel", "Mehta", "Iyer", "Kapoor",
    "Reddy", "Nair", "Malhotra", "Joshi", "Gupta",
    "Verma", "Desai",
]

QUALIFICATIONS = ["MBBS, MD", "MBBS, MS", "MBBS, DNB", "MBBS, DM"]
CITIES = ["Mumbai", "Pune", "Delhi", "Bengaluru", "Hyderabad", "Chennai"]


def build_doctors():
    """Build the doctor documents expected by the Flask application."""
    doctors = []
    created_at = datetime.utcnow()

    for index in range(300):
        specialty = SPECIALTIES[index % len(SPECIALTIES)]["name"]
        first_name = FIRST_NAMES[index % len(FIRST_NAMES)]
        last_name = LAST_NAMES[index // len(FIRST_NAMES)]
        number = index + 1
        number_text = f"{number:03d}"
        experience_years = 5 + (index % 16)
        consultation_fee = 500 + ((index % 8) * 100)

        doctors.append(
            {
                "name": f"Dr. {first_name} {last_name} {number_text}",
                "email": f"{SEEDED_EMAIL_PREFIX}{number_text}{SEEDED_EMAIL_DOMAIN}",
                # app.py currently checks doctor passwords as plain text.
                "password": DOCTOR_PASSWORD,
                "phone": f"+91-90000{number:05d}",
                "specialty": specialty,
                "gender": "Female" if index % 2 == 0 else "Male",
                "qualification": QUALIFICATIONS[index % len(QUALIFICATIONS)],
                "experience_years": experience_years,
                "experience": f"{experience_years} years",
                "consultation_fees": consultation_fee,
                "consultation_fee": consultation_fee,
                "consultation_type": "Online",
                "clinic_address": (
                    f"{CITIES[index % len(CITIES)]} Smart Health Clinic"
                ),
                "availability_status": "Available",
                "daily_patient_limit": 10,
                "leave_start_date": None,
                "leave_end_date": None,
                "busy_start_time": None,
                "busy_end_time": None,
                # Random User Generator supplies deterministic public portrait URLs.
                "image": (
                    "https://randomuser.me/api/portraits/"
                    f"{'women' if index % 2 == 0 else 'men'}/{index % 100}.jpg"
                ),
                "created_at": created_at,
            }
        )

    return doctors


def seed_database():
    """Insert specialties and replace only records created by this seed."""
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database = client[DATABASE_NAME]

    database.specialties.delete_many({})
    database.specialties.insert_many(SPECIALTIES)

    seeded_email_pattern = r"^doctor[0-9]{3}@smarthealth\.example$"
    database.doctor.delete_many({"email": {"$regex": seeded_email_pattern}})

    doctors = build_doctors()
    database.doctor.insert_many(doctors)

    print(f"Seeded {len(doctors)} doctors into {DATABASE_NAME}.doctor")
    print(f"Seeded {len(SPECIALTIES)} specialties into {DATABASE_NAME}.specialties")
    print("Doctor login email range: doctor001@smarthealth.example to "
          "doctor300@smarthealth.example")
    print(f"Doctor password: {DOCTOR_PASSWORD}")

    client.close()


if __name__ == "__main__":
    seed_database()
