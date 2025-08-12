import json
from typing import Dict, List, Any

class ConversationManager:
    def __init__(self, questions_path: str = "questions.json"):
        with open(questions_path, "r", encoding="utf-8") as f:
            self.questions: List[Dict[str, str]] = json.load(f)

    def first_question(self) -> str:
        return self.questions[0]["question"]

    def next_question(self, idx: int) -> str:
        if idx < len(self.questions):
            return self.questions[idx]["question"]
        return ""

    def num_questions(self) -> int:
        return len(self.questions)

    def build_structured_json(self, answers: Dict[str, str]) -> Dict[str, Any]:
        """
        相談シートの最終JSON（27項目対応版）。
        Google Sheets転記時に見やすい3セクション構成。
        """

        patient_info = {
            "ふりがな": answers.get("furigana", ""),
            "氏名": answers.get("patient_name", ""),
            "性別": answers.get("gender", ""),
            "生年月日": answers.get("dob", ""),
            "年齢": answers.get("age", ""),
            "住所（施設名含む）": answers.get("address", ""),
            "郵便番号": answers.get("postal_code", ""),
            "電話（自宅）": answers.get("home_phone", ""),
            "電話（携帯）": answers.get("mobile_phone", ""),
            "緊急連絡先電話番号": answers.get("emergency_contact", ""),
            "駐車場": answers.get("parking", ""),
            "居住形態": answers.get("residence_type", ""),
            "要介護度": answers.get("care_level", "")
        }

        medical_info = {
            "既往歴": answers.get("medical_history", ""),
            "現病歴": answers.get("current_condition", ""),
            "感染症": answers.get("infection_status", ""),
            "内科主治医_病院名": answers.get("internal_medicine_hospital", ""),
            "内科主治医_医師名": answers.get("internal_medicine_doctor", ""),
            "意思疎通": answers.get("communication_ability", ""),
            "嚥下機能": answers.get("swallowing_function", ""),
            "服薬状況": answers.get("medication_status", ""),
            "発症日・発症年": answers.get("onset_date", "")
        }

        coordination_info = {
            "希望訪問曜日・時間帯": answers.get("preferred_visit_time", ""),
            "同席者": answers.get("accompanying_person", ""),
            "キーパーソン_氏名": answers.get("key_person_name", ""),
            "キーパーソン_続柄": answers.get("key_person_relationship", ""),
            "キーパーソン_住所": answers.get("key_person_address", "")
        }

        return {
            "患者情報": patient_info,
            "医療情報": medical_info,
            "連絡・調整": coordination_info
        }
