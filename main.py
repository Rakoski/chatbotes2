import os

import requests
import json
import anthropic
import re

from dotenv import load_dotenv

load_dotenv()

WHATSAPP_API_URL = os.getenv('WHATSAPP_API_URL')
WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
RECIPIENT_PHONE_NUMBER = os.getenv('RECIPIENT_PHONE_NUMBER')

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
PRE_PROMPT = """
Você é o BipharmaBot, um assistente de farmácia que atende clientes via WhatsApp. 
Forneça respostas concisas e diretas sobre medicamentos comuns e orientações de uso. 
Destaque quando é necessário consultar um médico. 
Limite suas respostas a no máximo 90 caracteres no total.
Ao final, sempre inclua: 'Contato: (44) 998753-4343 www.bipharma.com.br/novo'
"""


def clean_text(text):
    text = text.replace('\n', ' ').replace('\t', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def get_anthropic_response(prompt):
    client = anthropic.Client(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-3-opus-20240229",
        max_tokens=1000,
        system=PRE_PROMPT,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return clean_text(response.content[0].text)


def split_response(response):
    words = response.split()
    parts = ['', '', '']
    current_part = 0

    for word in words:
        if len(parts[current_part] + word) <= 30:
            parts[current_part] += word + ' '
        elif current_part < 2:
            current_part += 1
            parts[current_part] = word + ' '
        else:
            break

    return [part.strip()[:30] for part in parts]


def send_whatsapp_message(claude_response):
    response_parts = split_response(claude_response)

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE_NUMBER,
        "type": "template",
        "template": {
            "name": "statement_available1",
            "language": {
                "code": "pt_BR"
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": response_parts[0]},
                        {"type": "text", "text": response_parts[1]},
                        {"type": "text", "text": response_parts[2]}
                    ]
                }
            ]
        }
    }

    response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
    return response.json()


def main():
    user_prompt = input("Digite sua pergunta: ")
    claude_response = get_anthropic_response(user_prompt)
    print("Resposta de Claude:", claude_response)
    whatsapp_response = send_whatsapp_message(claude_response)
    print("WhatsApp API response:", whatsapp_response)


if __name__ == "__main__":
    main()