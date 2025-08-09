import openai
import os
from openai import OpenAI
import json
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_structured_json(text):
    prompt = f"""
以下の相談内容をもとに、適切なJSON形式に変換してください。
必ずJSON形式のみを出力してください。余計な説明や補足は不要です。

---
{text}
---
出力フォーマット例:
{{
  "患者名": "",
  "希望内容": "",
  "症状": "",
  "緊急度": ""
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは医療事務の専門家です。自然文から必要情報を正確に構造化してください。出力は必ずJSON形式のみで返してください。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        json_text = response.choices[0].message.content.strip()

        # 👇 追加：GPTが返すコードブロック形式（```json）を除去
        if json_text.startswith("```json"):
            json_text = json_text.replace("```json", "").strip()
        if json_text.startswith("```"):
            json_text = json_text.replace("```", "", 1).strip()
        if json_text.endswith("```"):
            json_text = json_text[:-3].strip()

        print("🔽 GPTレスポンス内容:\n", json_text)
        return json.loads(json_text)

    except json.JSONDecodeError as e:
        print("❌ JSONパースエラー:", e)
        print("⚠️ 受け取った内容:\n", json_text)
        return None

    except Exception as e:
        print("❌ GPT処理エラー:", e)
        return None
