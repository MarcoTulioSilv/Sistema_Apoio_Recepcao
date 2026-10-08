-- Usuários de banco do SAR (DDS_recepcao, DD-58 e §12.3).
-- Um usuário por processo, com privilégio por tabela e, onde importa, por coluna.
-- Executado pela linha de comando `sar criar-usuarios-banco`, que substitui as senhas a partir dos
-- segredos do contêiner. As senhas nunca ficam neste arquivo nem no repositório.
-- Nenhum destes usuários existe na instância do SCE (RNF-614).

CREATE USER IF NOT EXISTS 'sar_web'@'%'     IDENTIFIED BY '{{SENHA_WEB}}';
CREATE USER IF NOT EXISTS 'sar_worker'@'%'  IDENTIFIED BY '{{SENHA_WORKER}}';
CREATE USER IF NOT EXISTS 'sar_expurgo'@'%' IDENTIFIED BY '{{SENHA_EXPURGO}}';
-- sar_migracao é criado na instalação, com ALL PRIVILEGES no banco, e usado só pelo contêiner de migração.
-- {{BANCO}} é o banco que recebe os privilégios: sar na aplicação; sar_teste para os testes em desenvolvimento.

-- =====================================================================================
-- sar_web — processo web
-- =====================================================================================
GRANT SELECT ON {{BANCO}}.* TO 'sar_web'@'%';

-- Tabelas de negócio editáveis pela aplicação
GRANT INSERT, UPDATE ON {{BANCO}}.usuario                 TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.sessao_usuario          TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.parametro               TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.instituicao             TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.convenio                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.paciente                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.contato                 TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.telefone                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.periodo_tratamento      TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.cobertura               TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.duplicidade_descartada  TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.rascunho_cadastro       TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.alocacao                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.troca_pontual           TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.extra_planejada         TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.termo_extra             TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.sessao_turno            TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.presenca                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.ligacao_manual          TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.ciencia_enfermagem      TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.ingestao                TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.solicitacao_autorizacao TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.modelo_documento        TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.requisicao_titular      TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.carga_lote              TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.carga_linha             TO 'sar_web'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.carga_conferencia       TO 'sar_web'@'%';

-- Só inserção: registros que nunca mudam
GRANT INSERT ON {{BANCO}}.municipio          TO 'sar_web'@'%';   -- DD-52: inclui, não altera
GRANT INSERT ON {{BANCO}}.mes_alterado       TO 'sar_web'@'%';   -- RF-915
GRANT INSERT ON {{BANCO}}.emissao_documento  TO 'sar_web'@'%';

-- Trilha de auditoria: inserção e avanço da cabeça; nunca alteração nem exclusão (RNF-609)
GRANT INSERT ON {{BANCO}}.auditoria                                       TO 'sar_web'@'%';
GRANT UPDATE (ultimo_registro_id, ultimo_hash) ON {{BANCO}}.auditoria_cabeca TO 'sar_web'@'%';
GRANT UPDATE (encerrado_em, encerrado_por, explicacao) ON {{BANCO}}.aviso_integridade TO 'sar_web'@'%';

-- Documento imutável (INV-06): arquivo, hash, chave e metadados de captura nunca mudam.
-- Atualização só em vínculo (RF-713), descarte (DD-04), bloqueio (P-19) e prova de encadeamento (DD-37).
GRANT INSERT ON {{BANCO}}.documento TO 'sar_web'@'%';
GRANT UPDATE (paciente_id, descartado_em, chave_cifrada, bloqueado_em, bloqueio_motivo, prova_encadeamento)
      ON {{BANCO}}.documento TO 'sar_web'@'%';

-- Exclusão física só onde a regra permite
GRANT DELETE ON {{BANCO}}.contato            TO 'sar_web'@'%';   -- edição do cadastro
GRANT DELETE ON {{BANCO}}.telefone           TO 'sar_web'@'%';
GRANT DELETE ON {{BANCO}}.rascunho_cadastro  TO 'sar_web'@'%';   -- rascunho vira paciente
GRANT DELETE ON {{BANCO}}.presenca           TO 'sar_web'@'%';   -- desmarcar exceção; anulação (DEC-61)
GRANT DELETE ON {{BANCO}}.ligacao_manual     TO 'sar_web'@'%';   -- refazer pareamento
GRANT DELETE ON {{BANCO}}.alocacao           TO 'sar_web'@'%';   -- alocação futura; anulação
GRANT DELETE ON {{BANCO}}.troca_pontual      TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON {{BANCO}}.extra_planejada    TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON {{BANCO}}.termo_extra        TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON {{BANCO}}.ciencia_enfermagem TO 'sar_web'@'%';   -- anulação
GRANT DELETE ON {{BANCO}}.carga_linha        TO 'sar_web'@'%';   -- aceite da carga (DD-69)
GRANT DELETE ON {{BANCO}}.carga_conferencia  TO 'sar_web'@'%';   -- aceite da carga (DD-69)

-- =====================================================================================
-- sar_worker — fila de ingestão e jobs
-- =====================================================================================
GRANT SELECT ON {{BANCO}}.* TO 'sar_worker'@'%';
GRANT INSERT ON {{BANCO}}.auditoria                                          TO 'sar_worker'@'%';
GRANT UPDATE (ultimo_registro_id, ultimo_hash) ON {{BANCO}}.auditoria_cabeca TO 'sar_worker'@'%';
GRANT INSERT ON {{BANCO}}.auditoria_ancora                                   TO 'sar_worker'@'%';
GRANT INSERT ON {{BANCO}}.aviso_integridade                                  TO 'sar_worker'@'%';
GRANT UPDATE ON {{BANCO}}.ingestao                                           TO 'sar_worker'@'%';
GRANT UPDATE (bloqueado_em, bloqueio_motivo) ON {{BANCO}}.documento          TO 'sar_worker'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.job_execucao                               TO 'sar_worker'@'%';
GRANT DELETE ON {{BANCO}}.rascunho_cadastro                                  TO 'sar_worker'@'%';

-- =====================================================================================
-- sar_expurgo — expurgo da trilha com mais de 5 anos (DEC-45, RNF-628)
-- =====================================================================================
GRANT SELECT, DELETE ON {{BANCO}}.auditoria      TO 'sar_expurgo'@'%';
GRANT SELECT, INSERT ON {{BANCO}}.auditoria_corte TO 'sar_expurgo'@'%';
GRANT SELECT ON {{BANCO}}.auditoria_ancora       TO 'sar_expurgo'@'%';
GRANT INSERT, UPDATE ON {{BANCO}}.job_execucao   TO 'sar_expurgo'@'%';
