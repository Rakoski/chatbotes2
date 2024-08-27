import os
import requests
import json
import anthropic
import re
import mysql.connector
from dotenv import load_dotenv
from flask import Flask, request, Response

load_dotenv()

WHATSAPP_API_URL = os.getenv('WHATSAPP_API_URL')
WHATSAPP_ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
WEBHOOK_VERIFY_TOKEN = os.getenv('WEBHOOK_VERIFY_TOKEN')
BIPHARMA_API_URL = os.getenv('BIPHARMA_API_URL')
BIPHARMA_API_KEY = os.getenv('BIPHARMA_API_KEY')

PRE_PROMPT = """
Você é o BipharmaBot, um assistente de farmácia que atende empresas de convênios parceiros via WhatsApp. 
Sua tarefa é extrair as seguintes informações da mensagem do usuário:
1. Nome da farmácia
2. Nome do vendedor
3. Nome do cliente ou ID do pedido
Forneça estas informações em formato JSON.
"""

DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = 'bipharma'

app = Flask(__name__)


def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )


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
    return json.loads(clean_text(response.content[0].text))


def get_bipharma_quotation(data):
    headers = {
        "Authorization": f"Bearer {BIPHARMA_API_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(BIPHARMA_API_URL, headers=headers, json=data)
    return response.json()


def send_whatsapp_message(phone_number, message):
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
    return response.json()


def save_order_to_db(order_data, quotation):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        insert_order = """
        INSERT INTO orders (order_id, pharmacy_name, seller_name, customer_name, total_value)
        VALUES (%s, %s, %s, %s, %s)
        """
        order_values = (
            order_data['order_id'],
            order_data['pharmacy_name'],
            order_data['seller_name'],
            order_data.get('customer_name', ''),
            quotation['total']
        )
        cursor.execute(insert_order, order_values)
        order_id = cursor.lastrowid

        # Inserir na tabela order_items
        insert_item = """
        INSERT INTO order_items (order_id, product_name, quantity, unit_price)
        VALUES (%s, %s, %s, %s)
        """
        for item in quotation['items']:
            item_values = (order_id, item['name'], item['quantity'], item['price'])
            cursor.execute(insert_item, item_values)

        conn.commit()
    except mysql.connector.Error as err:
        print(f"Erro ao salvar no banco de dados: {err}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def process_order(phone_number, order_data):
    quotation = get_bipharma_quotation(order_data)

    save_order_to_db(order_data, quotation)

    message = f"ORÇAMENTO\n{quotation['items']}\nValor Total: R$ {quotation['total']}\nOK PARA CONFIRMAR?"
    send_whatsapp_message(phone_number, message)


def confirm_order(phone_number, order_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        update_order = "UPDATE orders SET status = 'confirmed' WHERE order_id = %s"
        cursor.execute(update_order, (order_id,))
        conn.commit()

        headers = {
            "Authorization": f"Bearer {BIPHARMA_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {"order_id": order_id}
        response = requests.post(f"{BIPHARMA_API_URL}/confirm", headers=headers, json=data)

        if response.status_code == 200:
            send_whatsapp_message(phone_number, "Pedido confirmado e enviado para impressão.")
        else:
            send_whatsapp_message(phone_number, "Erro ao confirmar o pedido. Por favor, tente novamente.")

    except mysql.connector.Error as err:
        print(f"Erro ao confirmar pedido no banco de dados: {err}")
        send_whatsapp_message(phone_number, "Erro ao confirmar o pedido. Por favor, tente novamente.")
    finally:
        cursor.close()
        conn.close()


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode and token:
            if mode == 'subscribe' and token == WEBHOOK_VERIFY_TOKEN:
                return challenge
            else:
                return Response(status=403)

    elif request.method == 'POST':
        body = request.json

        for entry in body['entry']:
            for change in entry['changes']:
                if change['field'] == 'messages':
                    for message in change['value']['messages']:
                        if message['type'] == 'text':
                            phone_number = message['from']
                            message_body = message['text']['body']

                            if message_body.lower() == 'ok':
                                confirm_order(phone_number, phone_number)
                            else:
                                extracted_data = get_anthropic_response(message_body)
                                extracted_data[
                                    'order_id'] = phone_number
                                process_order(phone_number, extracted_data)

        return Response(status=200)


if __name__ == "__main__":
    app.run(port=8000)
