"""Interfaces dos repositórios do MOD-08: protocolos e objetos de transferência, sem SQLAlchemy.

Os outros módulos só podem importar daqui (o contrato "Só o MOD-08 fala com o banco" vale também para
imports indiretos). A implementação de cada interface fica em `repositorios/` e é ligada na raiz de
composição; os serviços a obtêm por `uow.repositorio(Interface)`.
"""
