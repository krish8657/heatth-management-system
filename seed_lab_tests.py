"""Seed hospitals and lab tests into the application's MongoDB database.

Run from the project directory:
    python seed_lab_tests.py

This creates hospitals with the fields required by the hospital dashboard and
lab tests with selectable hospitals for the patient booking page.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://tandelkrish628_db_user:6xatdUbleFqmCEPo@custer.7vkcxdn.mongodb.net/")
DATABASE_NAME = "health_db"

HOSPITALS = [
    ("Apollo Smart Health Hospital", "Mumbai"),
    ("Fortis Wellness Centre", "Delhi"),
    ("MaxCare Diagnostics", "Pune"),
    ("Narayana Health Labs", "Bengaluru"),
    ("Medanta Diagnostic Hospital", "Hyderabad"),
    ("Rainbow Health Diagnostics", "Chennai"),
]

TEST_DEFINITIONS = [
    ("Complete Blood Count (CBC)", "Hematology", 450, "24 hours", "Hemoglobin, WBC, RBC and platelet analysis"),
    ("Lipid Profile", "Biochemistry", 850, "24 hours", "Cholesterol and triglyceride assessment"),
    ("Liver Function Test", "Biochemistry", 900, "24 hours", "Liver enzymes and bilirubin assessment"),
    ("Kidney Function Test", "Biochemistry", 800, "24 hours", "Creatinine, urea and kidney health markers"),
    ("Thyroid Profile", "Hormone", 750, "24 hours", "TSH, T3 and T4 hormone levels"),
    ("HbA1c", "Diabetes", 550, "12 hours", "Average blood glucose over the previous months"),
    ("Fasting Blood Sugar", "Diabetes", 180, "6 hours", "Fasting glucose measurement"),
    ("Urine Routine Examination", "Pathology", 250, "12 hours", "Routine urine physical and microscopic analysis"),
    ("Vitamin D Test", "Vitamins", 1200, "48 hours", "25-hydroxy vitamin D level"),
    ("Vitamin B12 Test", "Vitamins", 1100, "48 hours", "Vitamin B12 level"),
    ("Chest X-Ray", "Radiology", 700, "24 hours", "Digital chest radiography"),
    ("Abdominal Ultrasound", "Radiology", 1500, "24 hours", "Ultrasound scan of abdominal organs"),
    ("ECG", "Cardiology", 500, "2 hours", "Electrocardiogram heart screening"),
    ("Echocardiogram", "Cardiology", 2500, "24 hours", "Ultrasound assessment of heart function"),
    ("COVID-19 RT-PCR", "Infectious Disease", 900, "24 hours", "Molecular respiratory infection test"),
]


def seed_database():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database = client[DATABASE_NAME]

    # Match the application's hospital database selection logic.
    hospital_database = database
    external_database = client["hospitals"]
    if "hospitals" in external_database.list_collection_names():
        hospital_database = external_database

    hospital_documents = []
    for index, (name, city) in enumerate(HOSPITALS, start=1):
        hospital_documents.append(
            {
                "name": name,
                "hospital_name": name,
                "email": f"lab{index:02d}@smarthealth.example",
                "password": "Hospital@123",
                "address": f"{city} Smart Health Campus",
                "city": city,
                "rating": round(4.1 + (index % 9) / 10, 1),
                "availability_status": "Available",
                "created_at": datetime.utcnow(),
            }
        )

    hospital_database.hospitals.delete_many(
        {"email": {"$regex": r"^lab[0-9]{2}@smarthealth\.example$"}}
    )
    hospital_result = hospital_database.hospitals.insert_many(hospital_documents)

    hospital_options = [
        {"hospital_id": str(identifier), "hospital_name": document["name"]}
        for identifier, document in zip(hospital_result.inserted_ids, hospital_documents)
    ]

    tests = []
    for name, category, price, delivery_time, parameters in TEST_DEFINITIONS:
        tests.append(
            {
                "name": name,
                "test_name": name,
                "category": category,
                "price": price,
                "cost": price,
                "parameters": parameters,
                "delivery_time": delivery_time,
                "available_at": [option["hospital_name"] for option in hospital_options],
                "hospitals": hospital_options,
                "created_at": datetime.utcnow(),
            }
        )

    database.lab_tests.delete_many(
        {"name": {"$in": [test["name"] for test in tests]}}
    )
    database.lab_tests.insert_many(tests)

    print(f"Seeded {len(hospital_documents)} hospitals into {hospital_database.name}.hospitals")
    print(f"Seeded {len(tests)} lab tests into {DATABASE_NAME}.lab_tests")
    print("Hospital login password for seeded accounts: Hospital@123")
    client.close()


if __name__ == "__main__":
    seed_database()
