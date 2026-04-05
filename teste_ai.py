import requests

URL = "http://localhost:8080/v1/chat/completions"

def perguntar(msg):
    payload = {
        "messages": [
            {
                "role": "system",
                "content": "Voce e uma streamer sarcastica e irritada. Fale informalmente."
            },
            {
                "role": "user",
                "content": msg
            }
        ],
        "temperature": 0.9,
        "max_tokens": 100
    }

    response = requests.post(URL, json=payload, timeout=120)

    print("STATUS:", response.status_code)
    print("RAW:", repr(response.text))  # MUITO IMPORTANTE

    response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    while True:
        msg = input("Voce: ")
        if msg.lower() == "sair":
            break

        try:
            resposta = perguntar(msg)
            print("IA:", resposta)

        except Exception as e:
            print("Erro:", e)