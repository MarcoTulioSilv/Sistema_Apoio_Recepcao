"""Agente de captura da estação da recepção (DDS §8.5, DD-39, DD-77 a DD-80, DD-98).

Programa pequeno e fechado, que roda na sessão do Windows da recepção (o WIA precisa de sessão de usuário): recebe do
navegador só a ingestão, o token e onde está o papel; digitaliza pelo scanner configurado; converte cada página de BMP
para PNG em memória; e a envia ao servidor do SAR por HTTPS, com o certificado raiz da clínica fixado. Nenhuma imagem
toca o disco da estação (SEG-28). Fica fora do pacote `sar`: tem dependências próprias e é empacotado em um .exe.
"""
