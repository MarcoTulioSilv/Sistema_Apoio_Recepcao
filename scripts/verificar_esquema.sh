#!/usr/bin/env bash
# Verifica, num banco de TESTE já migrado (0001 e 0002) e com os usuários criados, que as invariantes
# estruturais e os privilégios do DDS_recepcao (§6.4, §7.9, §12.3, DD-58) são garantidos pelo MySQL.
# Uso: ADMIN="-uroot" WEB_SENHA=... WORKER_SENHA=... EXPURGO_SENHA=... ./verificar_esquema.sh
# Nunca rode em produção: o script insere e apaga dados.
set -u
BANCO=${BANCO:-sar}
ADMIN=${ADMIN:--uroot}
falhas=0

sql_admin() { mysql $ADMIN "$BANCO" -N -e "$1" 2>&1 | grep -v Warning; }
sql_como() { mysql -u"$1" -p"$2" "$BANCO" -N -e "$3" 2>&1 | grep -v Warning; }

espera_erro() {  # descrição, saída, trecho esperado no erro
  if grep -q "$3" <<<"$2"; then echo "OK    $1"; else echo "FALHA $1 -> $2"; falhas=$((falhas+1)); fi
}
espera_valor() {  # descrição, saída, valor esperado na última linha
  if [ "$(tail -1 <<<"$2")" = "$3" ]; then echo "OK    $1"; else echo "FALHA $1 -> $2"; falhas=$((falhas+1)); fi
}

echo "== Preparação"
sql_admin "SET time_zone='+00:00';
  INSERT INTO usuario (nome, login, senha_hash, perfil, criado_em) VALUES ('Teste','teste', REPEAT('x',60), 'recepcao', NOW(6));
  INSERT INTO paciente (prontuario, nome, criado_em) VALUES ('T1','Paciente Um', NOW(6)), ('T2','Paciente Dois', NOW(6));
  INSERT INTO periodo_tratamento (paciente_id, inicio) SELECT id, '2026-01-01' FROM paciente WHERE prontuario='T1';"
P1=$(sql_admin "SELECT id FROM paciente WHERE prontuario='T1'")
P2=$(sql_admin "SELECT id FROM paciente WHERE prontuario='T2'")
U=$(sql_admin "SELECT id FROM usuario WHERE login='teste'")

echo "== Invariantes estruturais"
espera_erro "INV-02: segundo período aberto" \
  "$(sql_admin "INSERT INTO periodo_tratamento (paciente_id, inicio) VALUES ($P1,'2026-02-01')")" "uq_periodo_tratamento__um_aberto"
espera_valor "INV-02: encerrar e abrir outro" \
  "$(sql_admin "UPDATE periodo_tratamento SET evento_tipo='alta', evento_data='2026-03-01' WHERE paciente_id=$P1;
     INSERT INTO periodo_tratamento (paciente_id, inicio) VALUES ($P1,'2026-04-01');
     SELECT COUNT(*) FROM periodo_tratamento WHERE paciente_id=$P1")" "2"
espera_erro "Evento sem data" \
  "$(sql_admin "INSERT INTO periodo_tratamento (paciente_id, inicio, evento_tipo) VALUES ($P2,'2026-01-01','obito')")" "ck_periodo_tratamento__evento"
espera_erro "INV-12: telefone sem dono" \
  "$(sql_admin "INSERT INTO telefone (ddd, numero, tipo) VALUES ('64','999990000','celular')")" "ck_telefone__um_dono"
C=$(sql_admin "INSERT INTO contato (paciente_id, nome) VALUES ($P1,'Contato'); SELECT LAST_INSERT_ID()")
espera_erro "INV-12: telefone com dois donos" \
  "$(sql_admin "INSERT INTO telefone (paciente_id, contato_id, ddd, numero, tipo) VALUES ($P1,$C,'64','999990000','celular')")" "ck_telefone__um_dono"
espera_erro "INV-15: CPF repetido" \
  "$(sql_admin "UPDATE paciente SET cpf='12345678909' WHERE id=$P1; UPDATE paciente SET cpf='12345678909' WHERE id=$P2")" "uq_paciente__cpf"
espera_erro "CPF fora do formato" \
  "$(sql_admin "UPDATE paciente SET cpf='1234567890X' WHERE id=$P2")" "ck_paciente__cpf"
espera_erro "P-11: troca entre meses" \
  "$(sql_admin "INSERT INTO troca_pontual (paciente_id, data_origem, data_destino, escala_destino_id) VALUES ($P1,'2026-04-30','2026-05-02',2)")" "ck_troca_pontual__mesmo_mes"
espera_valor "Troca cancelada libera a mesma origem" \
  "$(sql_admin "INSERT INTO troca_pontual (paciente_id, data_origem, data_destino, escala_destino_id) VALUES ($P1,'2026-04-06','2026-04-07',2);
     UPDATE troca_pontual SET cancelada_em=NOW(6) WHERE paciente_id=$P1;
     INSERT INTO troca_pontual (paciente_id, data_origem, data_destino, escala_destino_id) VALUES ($P1,'2026-04-06','2026-04-09',2);
     SELECT COUNT(*) FROM troca_pontual WHERE paciente_id=$P1")" "2"
espera_erro "P-02: duas sessões ativas do mesmo usuário" \
  "$(sql_admin "INSERT INTO sessao_usuario (token_hash, usuario_id, origem, criada_em, ultimo_acesso) VALUES (REPEAT('a',64),$U,'x',NOW(6),NOW(6));
     INSERT INTO sessao_usuario (token_hash, usuario_id, origem, criada_em, ultimo_acesso) VALUES (REPEAT('b',64),$U,'x',NOW(6),NOW(6))")" "uq_sessao_usuario__uma_ativa"
espera_erro "Cobertura por convênio sem convênio" \
  "$(sql_admin "INSERT INTO cobertura (periodo_id, vigencia_inicio, tipo) SELECT id, '2026-04-01', 'convenio' FROM periodo_tratamento WHERE paciente_id=$P1 AND aberto=1")" "ck_cobertura__convenio"

echo "== Configuração de logs do servidor (DD-81, DD-82)"
espera_valor "binlog desligado (log_bin = 0)" "$(sql_admin "SELECT @@log_bin")" "0"
espera_valor "log geral desligado" "$(sql_admin "SELECT @@general_log")" "0"
espera_valor "log de consultas lentas desligado" "$(sql_admin "SELECT @@slow_query_log")" "0"

echo "== Privilégios (DD-58)"
sql_admin "INSERT INTO documento (id, paciente_id, tipo, versao, arquivo, chave_cifrada, nonce, hash_sha256, paginas, origem,
             capturado_em, capturado_por, local_digitalizacao)
           VALUES (UNHEX(REPLACE(UUID(),'-','')), $P1, 'cartao_sus', 1, 'teste-arquivo', x'00', x'000000000000000000000000',
             REPEAT('c',64), 1, 'scanner', NOW(6), $U, 'Teste');
           INSERT INTO auditoria (id, instante, operacao, entidade, versao_formato, hash_anterior, hash_registro)
           VALUES (999999999, NOW(6), 'teste', 'teste', 1, REPEAT('0',64), REPEAT('1',64));" >/dev/null
espera_erro "web: alterar hash do documento" "$(sql_como sar_web "$WEB_SENHA" "UPDATE documento SET hash_sha256=REPEAT('d',64) WHERE arquivo='teste-arquivo'")" "denied"
espera_erro "web: excluir documento" "$(sql_como sar_web "$WEB_SENHA" "DELETE FROM documento WHERE arquivo='teste-arquivo'")" "denied"
espera_valor "web: revincular documento" "$(sql_como sar_web "$WEB_SENHA" "UPDATE documento SET paciente_id=$P2 WHERE arquivo='teste-arquivo'; SELECT ROW_COUNT()")" "1"
espera_erro "web: alterar auditoria" "$(sql_como sar_web "$WEB_SENHA" "UPDATE auditoria SET motivo='x' WHERE id=999999999")" "denied"
espera_erro "web: excluir auditoria" "$(sql_como sar_web "$WEB_SENHA" "DELETE FROM auditoria WHERE id=999999999")" "denied"
espera_erro "web: excluir paciente" "$(sql_como sar_web "$WEB_SENHA" "DELETE FROM paciente WHERE id=$P2")" "denied"
espera_erro "web: alterar município" "$(sql_como sar_web "$WEB_SENHA" "UPDATE municipio SET nome='x'")" "denied"
espera_valor "web: travar a cabeça da cadeia" "$(sql_como sar_web "$WEB_SENHA" "START TRANSACTION;
     SELECT ultimo_registro_id FROM auditoria_cabeca WHERE id=1 FOR UPDATE; ROLLBACK; SELECT 'ok'")" "ok"
espera_erro "worker: excluir auditoria" "$(sql_como sar_worker "$WORKER_SENHA" "DELETE FROM auditoria WHERE id=999999999")" "denied"
espera_erro "worker: alterar hash do documento" "$(sql_como sar_worker "$WORKER_SENHA" "UPDATE documento SET hash_sha256=REPEAT('d',64)")" "denied"
espera_valor "worker: fila com SKIP LOCKED" "$(sql_como sar_worker "$WORKER_SENHA" "START TRANSACTION;
     SELECT id FROM ingestao WHERE estado='recebida' ORDER BY criada_em LIMIT 1 FOR UPDATE SKIP LOCKED; COMMIT; SELECT 'ok'")" "ok"
espera_erro "expurgo: alterar paciente" "$(sql_como sar_expurgo "$EXPURGO_SENHA" "UPDATE paciente SET nome='x'")" "denied"
espera_valor "expurgo: excluir auditoria" "$(sql_como sar_expurgo "$EXPURGO_SENHA" "DELETE FROM auditoria WHERE id=999999999; SELECT ROW_COUNT()")" "1"

echo "== Limpeza"
sql_admin "SET FOREIGN_KEY_CHECKS=0;
  DELETE FROM documento WHERE arquivo='teste-arquivo'; DELETE FROM troca_pontual WHERE paciente_id=$P1;
  DELETE FROM sessao_usuario WHERE usuario_id=$U; DELETE FROM contato WHERE paciente_id=$P1;
  DELETE FROM periodo_tratamento WHERE paciente_id IN ($P1,$P2); DELETE FROM paciente WHERE id IN ($P1,$P2);
  DELETE FROM usuario WHERE id=$U; UPDATE auditoria_cabeca SET ultimo_registro_id=0, ultimo_hash=REPEAT('0',64);
  SET FOREIGN_KEY_CHECKS=1;" >/dev/null

echo; [ "$falhas" -eq 0 ] && echo "Todas as verificações passaram." || echo "$falhas verificação(ões) falharam."
exit "$falhas"
