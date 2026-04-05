import threading

# True = IA está falando
# False = microfone liberado
ia_falando = threading.Event()
interromper_usuario = threading.Event()