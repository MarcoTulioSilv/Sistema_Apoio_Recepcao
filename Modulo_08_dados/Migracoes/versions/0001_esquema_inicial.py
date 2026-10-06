"""Esquema inicial do SAR.

Consolida as tabelas decididas no DDS_recepcao (§5 a §15) com as convenções da §12.2:
utf8mb4/utf8mb4_0900_ai_ci, instantes em DATETIME(6) UTC, hashes e tokens em ascii_bin,
identificadores aleatórios em BINARY(16), nomes de restrição padronizados, nenhum CASCADE.

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABELA = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"}


# ---------------------------------------------------------------- tipos auxiliares
def pk() -> sa.Column:
    return sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True)


def instante(nome: str, nulo: bool = False) -> sa.Column:
    return sa.Column(nome, mysql.DATETIME(fsp=6), nullable=nulo)


def uuid(nome: str, nulo: bool = False, **kw) -> sa.Column:
    return sa.Column(nome, mysql.BINARY(16), nullable=nulo, **kw)


def ascii_(nome: str, tamanho: int, nulo: bool = False, **kw) -> sa.Column:
    return sa.Column(nome, mysql.CHAR(tamanho, charset="ascii", collation="ascii_bin"), nullable=nulo, **kw)


def ref(nome: str, alvo: str, nulo: bool = False, tipo=None) -> sa.Column:
    """Chave estrangeira sem ação referencial (sem CASCADE, sem SET NULL). O nome é dado em criar()."""
    return sa.Column(nome, tipo if tipo is not None else mysql.BIGINT(unsigned=True),
                     sa.ForeignKey(alvo), nullable=nulo)


def usuario(nome: str, nulo: bool = False) -> sa.Column:
    return ref(nome, "usuario.id", nulo)


def versao() -> sa.Column:
    return sa.Column("versao", mysql.INTEGER(unsigned=True), nullable=False, server_default="1")


def marcador(nome: str, expressao: str) -> sa.Column:
    """Coluna gerada que vale 1 ou NULL; com índice único, garante 'no máximo um' só entre as linhas ativas."""
    return sa.Column(nome, mysql.TINYINT(unsigned=True), sa.Computed(expressao, persisted=True))


def criar(nome: str, *itens, **kw) -> None:
    """Cria a tabela nomeando toda chave estrangeira como fk_<tabela>__<coluna> (§12.2)."""
    for item in itens:
        if isinstance(item, sa.Column):
            for fk in item.foreign_keys:
                fk.name = f"fk_{nome}__{item.name}"
        elif isinstance(item, sa.ForeignKeyConstraint):
            item.name = f"fk_{nome}__{'_'.join(item.column_keys)}"
    op.create_table(nome, *itens, **TABELA, **kw)


# ---------------------------------------------------------------- upgrade
def upgrade() -> None:
    # ============ MOD-06 Configuração (referenciado por quase todos) ============
    criar("municipio",
          ascii_("codigo_ibge", 7, primary_key=True),
          sa.Column("nome", sa.String(80), nullable=False),
          ascii_("uf", 2),
          instante("incluido_em", nulo=True),
          sa.Column("incluido_por", mysql.BIGINT(unsigned=True), nullable=True),
          sa.CheckConstraint("codigo_ibge REGEXP '^[0-9]{7}$'", name="ck_municipio__codigo"),
          sa.Index("ix_municipio__uf_nome", "uf", "nome"))

    criar("usuario",
          pk(),
          sa.Column("nome", sa.String(120), nullable=False),
          sa.Column("login", sa.String(60), nullable=False),
          ascii_("senha_hash", 60),
          sa.Column("perfil", sa.Enum("recepcao", "administracao", "visualizador", "ti", "enfermagem",
                                      name="perfil"), nullable=False),
          sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.true()),
          sa.Column("deve_trocar_senha", sa.Boolean, nullable=False, server_default=sa.true()),
          instante("termo_ciencia_em", nulo=True),
          sa.Column("tentativas_falhas", mysql.SMALLINT(unsigned=True), nullable=False, server_default="0"),
          instante("bloqueado_ate", nulo=True),
          instante("criado_em"),
          versao(),
          sa.UniqueConstraint("login", name="uq_usuario__login"))

    op.create_foreign_key("fk_municipio__incluido_por", "municipio", "usuario",
                          ["incluido_por"], ["id"])

    criar("convenio",
          pk(),
          sa.Column("nome", sa.String(100), nullable=False),
          sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.true()),
          sa.UniqueConstraint("nome", name="uq_convenio__nome"))

    criar("instituicao",
          sa.Column("id", mysql.TINYINT(unsigned=True), primary_key=True, autoincrement=False),
          sa.Column("nome", sa.String(150), nullable=False),
          sa.Column("endereco", sa.String(200), nullable=False),
          ascii_("cep", 8),
          ref("municipio_id", "municipio.codigo_ibge", tipo=mysql.CHAR(7, charset="ascii", collation="ascii_bin")),
          ascii_("uf", 2),
          sa.Column("telefone", sa.String(20), nullable=True),
          ascii_("cnpj", 14, nulo=True),
          sa.Column("logotipo", mysql.MEDIUMBLOB, nullable=True),
          sa.Column("logotipo_tipo", sa.Enum("png", "jpeg", name="logotipo_tipo"), nullable=True),
          sa.CheckConstraint("id = 1", name="ck_instituicao__linha_unica"))

    criar("faixa_etaria",
          pk(),
          sa.Column("inicio", mysql.SMALLINT(unsigned=True), nullable=False),
          sa.Column("fim", mysql.SMALLINT(unsigned=True), nullable=True),
          sa.Column("rotulo", sa.String(20), nullable=False),
          sa.UniqueConstraint("inicio", name="uq_faixa_etaria__inicio"))

    criar("parametro",
          sa.Column("nome", sa.String(60), primary_key=True),
          sa.Column("valor", sa.String(200), nullable=False),
          instante("alterado_em"),
          usuario("alterado_por"))

    # ============ MOD-01 Acesso e auditoria ============
    criar("sessao_usuario",
          pk(),
          ascii_("token_hash", 64),
          usuario("usuario_id"),
          sa.Column("origem", sa.String(45), nullable=False),
          instante("criada_em"),
          instante("ultimo_acesso"),
          instante("encerrada_em", nulo=True),
          sa.Column("motivo_encerramento", sa.Enum("saida", "inatividade", "limite", "novo_login",
                                                   "inativacao", name="motivo_encerramento"), nullable=True),
          marcador("ativa", "IF(encerrada_em IS NULL, 1, NULL)"),
          sa.UniqueConstraint("token_hash", name="uq_sessao_usuario__token_hash"),
          # P-02: uma sessão ativa por usuário
          sa.UniqueConstraint("usuario_id", "ativa", name="uq_sessao_usuario__uma_ativa"))

    # O id da auditoria é atribuído pela aplicação a partir da cabeça da cadeia, sob trava (DD-03),
    # porque o próprio id entra no hash. Por isso não é autoincremento.
    criar("auditoria",
          sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=False),
          instante("instante"),
          usuario("usuario_id", nulo=True),
          usuario("autorizador_id", nulo=True),
          sa.Column("operacao", sa.String(80), nullable=False),
          sa.Column("entidade", sa.String(60), nullable=False),
          sa.Column("entidade_id", sa.String(40), nullable=True),
          sa.Column("alteracoes", mysql.MEDIUMTEXT, nullable=True),  # texto canônico, nunca JSON (§3.10)
          sa.Column("motivo", sa.String(500), nullable=True),
          sa.Column("origem", sa.String(45), nullable=True),
          sa.Column("versao_formato", mysql.SMALLINT(unsigned=True), nullable=False),
          ascii_("hash_anterior", 64),
          ascii_("hash_registro", 64),
          sa.UniqueConstraint("hash_registro", name="uq_auditoria__hash_registro"),
          sa.Index("ix_auditoria__entidade", "entidade", "entidade_id"),
          sa.Index("ix_auditoria__usuario_instante", "usuario_id", "instante"),
          sa.Index("ix_auditoria__instante", "instante"))

    criar("auditoria_cabeca",
          sa.Column("id", mysql.TINYINT(unsigned=True), primary_key=True, autoincrement=False),
          sa.Column("ultimo_registro_id", mysql.BIGINT(unsigned=True), nullable=False),
          ascii_("ultimo_hash", 64),
          sa.CheckConstraint("id = 1", name="ck_auditoria_cabeca__linha_unica"))

    criar("auditoria_ancora",
          pk(),
          sa.Column("ate_registro_id", mysql.BIGINT(unsigned=True), nullable=False),
          ascii_("hash", 64),
          instante("registrada_em"),
          instante("anotada_em", nulo=True),
          usuario("anotada_por", nulo=True))

    criar("auditoria_corte",
          pk(),
          sa.Column("primeiro_id_remanescente", mysql.BIGINT(unsigned=True), nullable=False),
          ascii_("hash_anterior", 64),
          instante("executado_em"),
          sa.Column("registros_expurgados", mysql.BIGINT(unsigned=True), nullable=False))

    criar("aviso_integridade",
          pk(),
          instante("detectado_em"),
          sa.Column("registro_divergente_id", mysql.BIGINT(unsigned=True), nullable=False),
          instante("encerrado_em", nulo=True),
          usuario("encerrado_por", nulo=True),
          sa.Column("explicacao", sa.Text, nullable=True),
          sa.CheckConstraint("(encerrado_em IS NULL) = (explicacao IS NULL)", name="ck_aviso_integridade__encerramento"))

    criar("solicitacao_autorizacao",
          uuid("id", primary_key=True),
          sa.Column("tipo", sa.String(80), nullable=False),
          sa.Column("entidade", sa.String(60), nullable=False),
          sa.Column("entidade_id", sa.String(40), nullable=False),
          sa.Column("parametros", sa.JSON, nullable=False),
          sa.Column("versao_alvo", mysql.INTEGER(unsigned=True), nullable=True),
          sa.Column("motivo", sa.String(500), nullable=False),
          usuario("solicitante_id"),
          instante("solicitada_em"),
          sa.Column("estado", sa.Enum("pendente", "executada", "invalidada", "recusada", "cancelada",
                                      name="estado_solicitacao"), nullable=False),
          usuario("decisor_id", nulo=True),
          instante("decidida_em", nulo=True),
          sa.Column("motivo_decisao", sa.String(500), nullable=True),
          sa.Index("ix_solicitacao_autorizacao__estado", "estado", "solicitada_em"))

    # ============ MOD-02 Cadastro ============
    municipio_fk = dict(tipo=mysql.CHAR(7, charset="ascii", collation="ascii_bin"))
    criar("paciente",
          pk(),
          sa.Column("prontuario", sa.String(20), nullable=False),          # P-03, INV-07
          sa.Column("nome", sa.String(150), nullable=False),
          sa.Column("data_nascimento", sa.Date, nullable=True),
          sa.Column("sexo", sa.Enum("F", "M", name="sexo"), nullable=True),
          sa.Column("nome_mae", sa.String(150), nullable=True),
          ascii_("cpf", 11, nulo=True),
          ascii_("cns", 15, nulo=True),
          sa.Column("rg", sa.String(20), nullable=True),
          sa.Column("rg_orgao", sa.String(20), nullable=True),
          ref("naturalidade_municipio_id", "municipio.codigo_ibge", nulo=True, **municipio_fk),
          sa.Column("logradouro", sa.String(150), nullable=True),
          sa.Column("numero", sa.String(10), nullable=True),
          sa.Column("complemento", sa.String(60), nullable=True),
          sa.Column("bairro", sa.String(80), nullable=True),
          ref("municipio_id", "municipio.codigo_ibge", nulo=True, **municipio_fk),
          ascii_("cep", 8, nulo=True),
          sa.Column("cep_verificado", sa.Boolean, nullable=False, server_default=sa.false()),
          instante("anulado_em", nulo=True),
          instante("criado_em"),
          versao(),
          sa.UniqueConstraint("prontuario", name="uq_paciente__prontuario"),
          sa.UniqueConstraint("cpf", name="uq_paciente__cpf"),          # INV-15
          sa.UniqueConstraint("cns", name="uq_paciente__cns"),          # INV-15
          sa.CheckConstraint("cpf REGEXP '^[0-9]{11}$'", name="ck_paciente__cpf"),
          sa.CheckConstraint("cns REGEXP '^[0-9]{15}$'", name="ck_paciente__cns"),
          sa.CheckConstraint("cep REGEXP '^[0-9]{8}$'", name="ck_paciente__cep"),
          sa.Index("ix_paciente__nome", "nome"),
          sa.Index("ix_paciente__nascimento", "data_nascimento"))

    criar("contato",
          pk(),
          ref("paciente_id", "paciente.id"),
          sa.Column("nome", sa.String(150), nullable=False),
          sa.Column("parentesco", sa.String(40), nullable=True))

    criar("telefone",
          pk(),
          ref("paciente_id", "paciente.id", nulo=True),
          ref("contato_id", "contato.id", nulo=True),
          ascii_("ddd", 2),
          sa.Column("numero", sa.String(9), nullable=False),
          sa.Column("tipo", sa.Enum("celular", "fixo", "recado", name="tipo_telefone"), nullable=False),
          # INV-12, DD-06: exatamente um dono
          sa.CheckConstraint("(paciente_id IS NULL) <> (contato_id IS NULL)", name="ck_telefone__um_dono"))

    # Evento embutido no período (DD-13). O FK do comprovante é criado depois de `documento`.
    criar("periodo_tratamento",
          pk(),
          ref("paciente_id", "paciente.id"),
          sa.Column("inicio", sa.Date, nullable=False),
          sa.Column("medico_referencia", sa.String(150), nullable=True),
          sa.Column("evento_tipo", sa.Enum("obito", "alta", "transferencia", "transplante", "desistencia",
                                           name="tipo_evento"), nullable=True),
          sa.Column("evento_data", sa.Date, nullable=True),
          sa.Column("evento_local", sa.String(150), nullable=True),
          uuid("evento_documento_id", nulo=True),
          instante("evento_registrado_em", nulo=True),
          marcador("aberto", "IF(evento_tipo IS NULL, 1, NULL)"),
          # INV-02: no máximo um período aberto por paciente
          sa.UniqueConstraint("paciente_id", "aberto", name="uq_periodo_tratamento__um_aberto"),
          sa.UniqueConstraint("paciente_id", "inicio", name="uq_periodo_tratamento__inicio"),
          sa.CheckConstraint("(evento_tipo IS NULL) = (evento_data IS NULL)", name="ck_periodo_tratamento__evento"),
          sa.CheckConstraint("evento_data IS NULL OR evento_data >= inicio", name="ck_periodo_tratamento__datas"),
          sa.CheckConstraint("evento_documento_id IS NULL OR evento_tipo IS NOT NULL",
                             name="ck_periodo_tratamento__comprovante"))

    # Cobertura só com início (fim derivado da seguinte): INV-09 garantida por construção (DD-70).
    criar("cobertura",
          pk(),
          ref("periodo_id", "periodo_tratamento.id"),
          sa.Column("vigencia_inicio", sa.Date, nullable=False),
          sa.Column("tipo", sa.Enum("sus", "convenio", name="tipo_cobertura"), nullable=False),
          ref("convenio_id", "convenio.id", nulo=True),
          sa.Column("carteirinha", sa.String(30), nullable=True),
          sa.UniqueConstraint("periodo_id", "vigencia_inicio", name="uq_cobertura__inicio"),
          sa.CheckConstraint("(tipo = 'convenio') = (convenio_id IS NOT NULL)", name="ck_cobertura__convenio"))

    criar("duplicidade_descartada",
          pk(),
          ref("paciente_a_id", "paciente.id"),
          ref("paciente_b_id", "paciente.id"),
          usuario("decidido_por"),
          instante("decidido_em"),
          sa.UniqueConstraint("paciente_a_id", "paciente_b_id", name="uq_duplicidade_descartada__par"),
          sa.CheckConstraint("paciente_a_id < paciente_b_id", name="ck_duplicidade_descartada__ordem"))

    criar("rascunho_cadastro",
          pk(),
          usuario("usuario_id"),
          sa.Column("conteudo_cifrado", mysql.MEDIUMBLOB, nullable=False),
          sa.Column("nonce", mysql.BINARY(12), nullable=False),
          instante("criado_em"),
          instante("atualizado_em"),
          sa.UniqueConstraint("usuario_id", name="uq_rascunho_cadastro__usuario"))

    # ============ MOD-04 Documentos ============
    criar("tipo_documento",
          sa.Column("codigo", sa.String(40), primary_key=True),
          sa.Column("nome", sa.String(120), nullable=False),
          sa.Column("familia", sa.Enum("cadastro", "prontuario", name="familia"), nullable=False),
          sa.Column("anos_retencao", mysql.SMALLINT(unsigned=True), nullable=False),
          sa.Column("checklist", sa.Enum("nao", "sempre", "se_convenio", name="checklist"), nullable=False),
          sa.Column("evento_exigente", sa.Enum("obito", "alta", "transferencia", "transplante", "desistencia",
                                               name="tipo_evento"), nullable=True),
          sa.Column("origem", sa.Enum("scanner", "webcam", name="origem_captura"), nullable=False),
          sa.Column("campos_extracao", sa.String(200), nullable=True))

    tipo_fk = dict(tipo=sa.String(40))
    criar("documento",
          uuid("id", primary_key=True),
          ref("paciente_id", "paciente.id"),
          ref("tipo", "tipo_documento.codigo", **tipo_fk),
          sa.Column("versao", mysql.SMALLINT(unsigned=True), nullable=False),
          uuid("substitui_id", nulo=True),
          ascii_("arquivo", 36),
          sa.Column("chave_cifrada", mysql.VARBINARY(128), nullable=True),   # NULL após descarte (DD-04)
          sa.Column("nonce", mysql.BINARY(12), nullable=False),
          ascii_("hash_sha256", 64),
          ascii_("prova_encadeamento", 64, nulo=True),                        # preenchida no commit (DD-37)
          sa.Column("paginas", mysql.SMALLINT(unsigned=True), nullable=False),
          sa.Column("origem", sa.Enum("scanner", "webcam", name="origem_captura"), nullable=False),
          instante("capturado_em"),
          usuario("capturado_por"),
          sa.Column("local_digitalizacao", sa.String(80), nullable=False),   # DD-11
          instante("descartado_em", nulo=True),
          instante("bloqueado_em", nulo=True),
          sa.Column("bloqueio_motivo", sa.Enum("rescan", "hash_divergente", name="motivo_bloqueio"), nullable=True),
          sa.UniqueConstraint("arquivo", name="uq_documento__arquivo"),
          sa.UniqueConstraint("hash_sha256", name="uq_documento__hash"),
          sa.UniqueConstraint("substitui_id", name="uq_documento__substitui"),
          sa.ForeignKeyConstraint(["substitui_id"], ["documento.id"]),
          sa.CheckConstraint("(descartado_em IS NULL) = (chave_cifrada IS NOT NULL)", name="ck_documento__descarte"),
          sa.CheckConstraint("(bloqueado_em IS NULL) = (bloqueio_motivo IS NULL)", name="ck_documento__bloqueio"),
          sa.Index("ix_documento__paciente_tipo", "paciente_id", "tipo"))

    op.create_foreign_key("fk_periodo_tratamento__evento_documento_id", "periodo_tratamento", "documento",
                          ["evento_documento_id"], ["id"])

    criar("ingestao",
          uuid("id", primary_key=True),
          ref("paciente_id", "paciente.id"),
          ref("tipo", "tipo_documento.codigo", **tipo_fk),
          sa.Column("origem", sa.Enum("scanner", "webcam", name="origem_captura"), nullable=False),
          sa.Column("vinculo", sa.String(80), nullable=True),
          uuid("substitui_id", nulo=True),
          sa.Column("estado", sa.Enum("aberta", "recebida", "em_processamento", "aguardando_conferencia",
                                      "incorporada", "rejeitada", "expirada", "cancelada",
                                      name="estado_ingestao"), nullable=False),
          sa.Column("motivo_rejeicao", sa.String(60), nullable=True),
          ascii_("token_hash", 64, nulo=True),
          ascii_("hash_entrada", 64, nulo=True),
          ascii_("hash_reconstruido", 64, nulo=True),
          sa.Column("paginas", mysql.SMALLINT(unsigned=True), nullable=True),
          sa.Column("campos_candidatos_cifrados", sa.LargeBinary, nullable=True),   # P-18
          uuid("documento_id", nulo=True),
          instante("criada_em"),
          usuario("criada_por"),
          instante("atualizada_em"),
          sa.ForeignKeyConstraint(["substitui_id"], ["documento.id"]),
          sa.ForeignKeyConstraint(["documento_id"], ["documento.id"]),
          sa.UniqueConstraint("token_hash", name="uq_ingestao__token_hash"),
          sa.UniqueConstraint("documento_id", name="uq_ingestao__documento"),
          sa.CheckConstraint("estado = 'aguardando_conferencia' OR campos_candidatos_cifrados IS NULL",
                             name="ck_ingestao__candidatos"),
          sa.Index("ix_ingestao__fila", "estado", "criada_em"))

    # ============ MOD-03 Operação ============
    criar("escala",
          sa.Column("id", mysql.TINYINT(unsigned=True), primary_key=True, autoincrement=False),
          ascii_("codigo", 5),
          sa.Column("turno", mysql.TINYINT(unsigned=True), nullable=False),
          sa.Column("dias", sa.String(20), nullable=False),
          sa.Column("hora_inicio", sa.Time, nullable=False),
          sa.Column("hora_fim", sa.Time, nullable=False),
          sa.UniqueConstraint("codigo", name="uq_escala__codigo"))

    escala_fk = dict(tipo=mysql.TINYINT(unsigned=True))
    criar("alocacao",
          pk(),
          ref("periodo_id", "periodo_tratamento.id"),
          ref("escala_id", "escala.id", nulo=True, **escala_fk),          # NULL = sem alocação (DD-27)
          sa.Column("vigencia_inicio", sa.Date, nullable=False),
          sa.UniqueConstraint("periodo_id", "vigencia_inicio", name="uq_alocacao__inicio"))

    criar("troca_pontual",
          pk(),
          ref("paciente_id", "paciente.id"),
          sa.Column("data_origem", sa.Date, nullable=False),
          sa.Column("data_destino", sa.Date, nullable=False),
          ref("escala_destino_id", "escala.id", **escala_fk),
          uuid("documento_id", nulo=True),
          instante("cancelada_em", nulo=True),
          sa.Column("cancelada_motivo", sa.String(300), nullable=True),
          marcador("ativa", "IF(cancelada_em IS NULL, 1, NULL)"),
          sa.ForeignKeyConstraint(["documento_id"], ["documento.id"]),
          sa.UniqueConstraint("paciente_id", "data_origem", "ativa", name="uq_troca_pontual__origem"),
          # P-11: origem e destino no mesmo mês
          sa.CheckConstraint("EXTRACT(YEAR_MONTH FROM data_origem) = EXTRACT(YEAR_MONTH FROM data_destino)",
                             name="ck_troca_pontual__mesmo_mes"))

    criar("extra_planejada",
          pk(),
          ref("paciente_id", "paciente.id"),
          sa.Column("data", sa.Date, nullable=False),
          ref("escala_id", "escala.id", **escala_fk),
          instante("cancelada_em", nulo=True),
          sa.Column("cancelada_motivo", sa.String(300), nullable=True),
          marcador("ativa", "IF(cancelada_em IS NULL, 1, NULL)"),
          sa.UniqueConstraint("paciente_id", "data", "escala_id", "ativa", name="uq_extra_planejada__sessao"))

    criar("termo_extra",
          pk(),
          ref("paciente_id", "paciente.id"),
          ascii_("competencia", 7),
          uuid("documento_id"),
          sa.ForeignKeyConstraint(["documento_id"], ["documento.id"]),
          sa.UniqueConstraint("paciente_id", "competencia", name="uq_termo_extra__competencia"),
          sa.CheckConstraint("competencia REGEXP '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_termo_extra__competencia"))

    criar("sessao_turno",
          pk(),
          sa.Column("data", sa.Date, nullable=False),
          ref("escala_id", "escala.id", **escala_fk),
          instante("confirmada_em", nulo=True),
          usuario("confirmada_por", nulo=True),
          sa.Column("nao_realizada_motivo", sa.String(300), nullable=True),   # P-12
          versao(),
          sa.UniqueConstraint("data", "escala_id", name="uq_sessao_turno__data_escala"),
          sa.CheckConstraint("(confirmada_em IS NULL) = (confirmada_por IS NULL)", name="ck_sessao_turno__confirmacao"),
          sa.CheckConstraint("nao_realizada_motivo IS NULL OR confirmada_em IS NOT NULL",
                             name="ck_sessao_turno__nao_realizada"))

    criar("presenca",
          pk(),
          ref("sessao_id", "sessao_turno.id"),
          ref("paciente_id", "paciente.id"),
          sa.Column("situacao", sa.Enum("presente", "ausente", name="situacao_presenca"), nullable=False),
          sa.UniqueConstraint("sessao_id", "paciente_id", name="uq_presenca__sessao_paciente"),
          sa.Index("ix_presenca__paciente", "paciente_id"))

    criar("ligacao_manual",
          pk(),
          ref("ausencia_id", "presenca.id"),
          ref("presenca_id", "presenca.id"),
          usuario("criada_por"),
          instante("criada_em"),
          sa.UniqueConstraint("ausencia_id", name="uq_ligacao_manual__ausencia"),
          sa.UniqueConstraint("presenca_id", name="uq_ligacao_manual__presenca"),
          sa.CheckConstraint("ausencia_id <> presenca_id", name="ck_ligacao_manual__distintas"))

    criar("ciencia_enfermagem",
          sa.Column("presenca_id", mysql.BIGINT(unsigned=True),
                    sa.ForeignKey("presenca.id"), primary_key=True),
          instante("registrada_em"),
          usuario("registrada_por"))

    criar("mes_alterado",
          pk(),
          ascii_("competencia", 7),
          instante("instante"),
          usuario("responsavel_id"),
          usuario("autorizador_id"),
          sa.Column("motivo", sa.String(500), nullable=False),
          uuid("solicitacao_id", nulo=True),
          sa.ForeignKeyConstraint(["solicitacao_id"], ["solicitacao_autorizacao.id"]),
          sa.CheckConstraint("competencia REGEXP '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_mes_alterado__competencia"),
          sa.Index("ix_mes_alterado__competencia", "competencia"))

    # ============ MOD-05 Emissão ============
    criar("modelo_documento",
          pk(),
          sa.Column("codigo", sa.String(20), nullable=False),
          sa.Column("versao", mysql.INTEGER(unsigned=True), nullable=False),
          sa.Column("arquivo", mysql.MEDIUMBLOB, nullable=False),
          ascii_("hash_sha256", 64),
          instante("enviado_em"),
          usuario("enviado_por"),
          sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.false()),
          instante("ativado_em", nulo=True),
          usuario("ativado_por", nulo=True),
          marcador("ativo_marcador", "IF(ativo, 1, NULL)"),
          sa.UniqueConstraint("codigo", "versao", name="uq_modelo_documento__versao"),
          sa.UniqueConstraint("codigo", "ativo_marcador", name="uq_modelo_documento__um_ativo"))

    criar("emissao_documento",
          pk(),
          ref("paciente_id", "paciente.id"),
          sa.Column("modelo", sa.String(20), nullable=False),
          sa.Column("versao_modelo", mysql.INTEGER(unsigned=True), nullable=False),
          sa.Column("referencia", sa.String(40), nullable=True),
          ascii_("competencia", 7),
          instante("emitido_em"),
          usuario("emitido_por"),
          sa.Index("ix_emissao_documento__aviso", "paciente_id", "modelo", "competencia"))

    # ============ MOD-09 Agendamento ============
    criar("job_execucao",
          pk(),
          sa.Column("job", sa.String(60), nullable=False),
          instante("inicio"),
          instante("fim", nulo=True),
          sa.Column("resultado", sa.Enum("em_andamento", "sucesso", "falha", "sem_trabalho",
                                         name="resultado_job"), nullable=False),
          sa.Column("itens", mysql.INTEGER(unsigned=True), nullable=True),
          sa.Column("resumo_erro", sa.String(300), nullable=True),   # sem dado pessoal (RNF-624)
          sa.Index("ix_job_execucao__job_inicio", "job", "inicio"))

    # ============ MOD-10 Carga inicial ============
    criar("carga_lote",
          pk(),
          sa.Column("modo", sa.Enum("simulacao", "efetivacao", name="modo_carga"), nullable=False),
          sa.Column("situacao", sa.Enum("em_andamento", "concluida", "falhou", "aceita", name="situacao_carga"),
                    nullable=False),
          sa.Column("contagens", sa.JSON, nullable=True),
          instante("iniciado_em"),
          instante("concluido_em", nulo=True),
          instante("aceito_em", nulo=True),
          usuario("aceito_por", nulo=True),
          marcador("efetivacao_valida", "IF(modo = 'efetivacao' AND situacao <> 'falhou', 1, NULL)"),
          sa.UniqueConstraint("efetivacao_valida", name="uq_carga_lote__uma_efetivacao"))

    criar("carga_linha",
          pk(),
          ref("lote_id", "carga_lote.id"),
          sa.Column("planilha", sa.String(40), nullable=False),
          sa.Column("numero_linha", mysql.INTEGER(unsigned=True), nullable=False),
          sa.Column("conteudo_cifrado", mysql.MEDIUMBLOB, nullable=False),
          sa.Column("nonce", mysql.BINARY(12), nullable=False),
          ref("paciente_id", "paciente.id", nulo=True),
          sa.Column("excecao_codigo", sa.String(40), nullable=True),
          sa.Column("excecao_tratada", sa.Enum("importada_manual", "descartada", name="tratamento_excecao"),
                    nullable=True),
          sa.Column("excecao_motivo", sa.String(300), nullable=True),
          sa.UniqueConstraint("lote_id", "planilha", "numero_linha", name="uq_carga_linha__origem"))

    criar("carga_conferencia",
          pk(),
          ref("paciente_id", "paciente.id"),
          sa.Column("campo", sa.String(40), nullable=False),
          sa.Column("resultado", sa.Enum("conferido", "divergente", name="resultado_conferencia"), nullable=False),
          usuario("conferido_por"),
          instante("conferido_em"),
          sa.UniqueConstraint("paciente_id", "campo", name="uq_carga_conferencia__campo"))

    # ============ MOD-11 Atendimento ao titular ============
    criar("requisicao_titular",
          pk(),
          ref("paciente_id", "paciente.id"),
          sa.Column("tipo", sa.Enum("confirmacao_acesso", "correcao", "informacao", "eliminacao", "outros",
                                    name="tipo_requisicao"), nullable=False),
          sa.Column("canal", sa.String(40), nullable=False),
          instante("recebida_em"),
          sa.Column("situacao", sa.Enum("aberta", "atendida", "negada", name="situacao_requisicao"), nullable=False),
          sa.Column("desfecho", sa.Text, nullable=True),
          instante("atendida_em", nulo=True),
          usuario("atendente_id", nulo=True),
          sa.Index("ix_requisicao_titular__situacao", "situacao", "recebida_em"))


def downgrade() -> None:
    """Só até o go-live (DD-60). Remove na ordem inversa das dependências."""
    for tabela in [
        "requisicao_titular", "carga_conferencia", "carga_linha", "carga_lote", "job_execucao",
        "emissao_documento", "modelo_documento", "mes_alterado", "ciencia_enfermagem", "ligacao_manual",
        "presenca", "sessao_turno", "termo_extra", "extra_planejada", "troca_pontual", "alocacao", "escala",
        "ingestao",
    ]:
        op.drop_table(tabela)
    op.drop_constraint("fk_periodo_tratamento__evento_documento_id", "periodo_tratamento", type_="foreignkey")
    for tabela in [
        "documento", "tipo_documento", "rascunho_cadastro", "duplicidade_descartada", "cobertura",
        "periodo_tratamento", "telefone", "contato", "paciente", "solicitacao_autorizacao", "aviso_integridade",
        "auditoria_corte", "auditoria_ancora", "auditoria_cabeca", "auditoria", "sessao_usuario", "parametro",
        "faixa_etaria", "instituicao", "convenio",
    ]:
        op.drop_table(tabela)
    op.drop_constraint("fk_municipio__incluido_por", "municipio", type_="foreignkey")
    op.drop_table("usuario")
    op.drop_table("municipio")
