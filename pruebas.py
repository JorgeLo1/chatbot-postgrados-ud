import requests

response = requests.post(
    "https://chatbot-postgrados-ud.onrender.com/webhooks/rest/webhook",
    json={"sender": "usuario_prueba", "message": "hola"}
)

print(response.json())
