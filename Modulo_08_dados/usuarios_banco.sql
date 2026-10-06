-- Usuários de banco do SAR (DDS_recepcao, DD-58 e §12.3).
-- Um usuário por processo, com privilégio por tabela e, onde importa, por coluna.
-- Executado pela linha de comando `sar criar-usuarios-banco`, que substitui as senhas a partir dos
-- segredos do contêiner. As senhas nunca ficam neste arquivo nem no repositório.
-- Nenhum destes usuários existe na instância do SCE (RNF-614).

CREATE USER IF NOT EXISTS 'sar_web'@'%'     IDENTIFIED BY '{{SENHA_WEB}}';
CREATE USER IF NOT EXISTS 'sar_worker'@'%'  IDENTIFIED BY '{{SENHA_WORKER}}';
CREATE USER IF NOT EXISTS 'sar_expurgo'@'%' IDENTIFIED BY '{{SENHA_EXPURGO}}';
-- sar_migracao é criado na instalação, com ALL PRIVILEGES em sar.*, e usado só pelo contêiner de migração.

-- =====================================================================================
-- sar_web — processo web
-- =====================================================================================
GRANT SELECT ON sar.* TO 'sar_web'@'%';

-- Tabelas de negócio editáveis pela aplicação
GRANT INSERT, UPDATE ON sar.usuario                 TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.sessao_usuario          TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.parametro               TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.instituicao             TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.convenio                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.paciente                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.contato                 TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.telefone                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.periodo_tratamento      TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.cobertura               TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.duplicidade_descartada  TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.rascunho_cadastro       TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.alocacao                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.troca_pontual           TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.extra_planejada         TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.termo_extra             TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.sessao_turno            TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.presenca                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.ligacao_manual          TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.ciencia_enfermagem      TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.ingestao                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.solicitacao_autorizacao TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.modelo_documento        TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.requisicao_titular      TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.carga_lote              TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.carga_linha             TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON sar.carga_conferencia       TO 'sar_web'@'%';

-- Só inserção: registros que nunca mudam
GRANT INSERT ON sar.municipio          TO 'sar_web'@'%';   -- DD-52: inclui, não altera
GRANT INSERT ON sar.mes_alterado       TO 'sar_web'@'%';   -- RF-915
GRANT INSERT ON sar.emissao_documento  TO 'sar_web'@'%';

-- Trilha de auditoria: inserção e avanço da cabeça; nunca alteração nem exclusão (RNF-609)
GRANT INSERT ON sar.auditoria                                       TO 'sar_web'@'%';
GRANT UPDATE (ultimo_registro_id, ultimo_hash) ON sar.auditoria_cabeca TO 'sar_web'@'%';
GRANT UPDATE (anotada_em, anotada_por) ON sar.auditoria_ancora      TO 'sar_web'@'%';   -- pendência 20
GRANT UPDATE (encerrado_em, encerrado_por, explicacao) ON sar.aviso_integridade TO 'sar_web'@'%';

-- Documento imutável (INV-06): arquivo, hash, chave e metadados de captura nunca mudam.
-- Atualização só em vínculo (RF-713), descarte (DD-04), bloqueio (P-19) e prova de encadeamento (DD-37).
GRANT INSERT ON sar.documento TO 'sar_web'@'%';
GRANT UPDATE (paciente_id, descartado_em, chave_cifrada, bloqueado_em, bloqueio_motivo, prova_encadeamento)
      ON sar.documento TO 'sar_web'@'%';

-- Exclusão física só onde a regra permite
GRANT DELETE ON sar.contato            TO 'sar_web'@'%';   -- edição do cadastro
GRANT DELETE ON sar.telefone           TO 'sar_web'@'%';
GRANT DELETE ON sar.rascunho_cadastro  TO 'sar_web'@'%';   -- rascunho vira paciente
GRANT DELETE ON sar.presenca           TO 'sar_web'@'%';   -- desmarcar exceção; anulação (DEC-61)
GRANT DELETE ON sar.ligacao_manual     TO 'sar_web'@'%';   -- refazer pareamento
GRANT DELETE ON sar.alocacao           TO 'sar_web'@'%';   -- alocação futura; anulação
GRANT DELETE ON sar.troca_pontual      TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON sar.extra_planejada    TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON sar.termo_extra        TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON sar.ciencia_enfermagem TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON sar.carga_linha        TO 'sar_web'@'%';   -- aceite da carga (DD-69)
GRANT DELETE ON sar.carga_conferencia  TO 'sar_web'@'%';   -- aceite da carga (DD-69)

-- =====================================================================================
-- sar_worker — fila de ingestão e jobs
-- =====================================================================================
GRANT SELECT ON sar.* TO 'sar_worker'@'%';
GRANT INSERT ON sar.auditoria                                          TO 'sar_worker'@'%';
GRANT UPDATE (ultimo_registro_id, ultimo_hash) ON sar.auditoria_cabeca TO 'sar_worker'@'%';
GRANT INSERT ON sar.auditoria_ancora                                   TO 'sar_worker'@'%';
GRANT INSERT ON sar.aviso_integridade                                  TO 'sar_worker'@'%';
GRANT UPDATE ON sar.ingestao                                           TO 'sar_worker'@'%';
GRANT UPDATE (bloqueado_em, bloqueio_motivo) ON sar.documento          TO 'sar_worker'@'%';
GRANT INSERT, UPDATE ON sar.job_execucao                               TO 'sar_worker'@'%';
GRANT DELETE ON sar.rascunho_cadastro                                  TO 'sar_worker'@'%';

-- =====================================================================================
-- sar_expurgo — expurgo da trilha com mais de 5 anos (DEC-45, RNF-628)
-- =====================================================================================
GRANT SELECT, DELETE ON sar.auditoria      TO 'sar_expurgo'@'%';
GRANT SELECT, INSERT ON sar.auditoria_corte TO 'sar_expurgo'@'%';
GRANT SELECT ON sar.auditoria_ancora       TO 'sar_expurgo'@'%';
GRANT INSERT, UPDATE ON sar.job_execucao   TO 'sar_expurgo'@'%';
