# Extensão do Chrome — leitor de odds da Novibet

Esta extensão é a Opção B do projeto ([decisões D-018](../docs/decisoes.md#d-018)).
Você abre as páginas de torneio da Novibet no **seu** Chrome, do jeito normal.
A extensão copia as odds que a página já recebeu e entrega ao bot, que roda
neste mesmo computador.

## O que ela faz e o que ela não faz

| Faz | Não faz |
|---|---|
| Copia as respostas de odds que a página da Novibet pediu sozinha | Não faz nenhuma requisição ao site |
| Manda essas cópias para o bot em `127.0.0.1` (este computador) | Não manda nada para a internet |
| Avisa o bot se a aba mostrar tela de verificação | Não resolve verificação, não clica, não recarrega a página |
| | Não faz login e não aposta |

Se aparecer a tela de verificação da Cloudflare, **quem resolve é você**,
como faria em qualquer site. Se ela não passar, a fonte fica desligada. O bot
nunca tenta passar por ela.

## Instalar (uma vez)

1. No Chrome, abra `chrome://extensions`.
2. Ligue **Modo do desenvolvedor** (canto superior direito).
3. Clique em **Carregar sem compactação** e escolha esta pasta (`extensao`).
4. A extensão "Projeto Novibet - leitor de odds" aparece na lista.

Se esta pasta mudar (depois de um `git pull`), volte em `chrome://extensions`
e clique no botão de recarregar da extensão. Depois recarregue as abas da
Novibet.

## Usar

1. No `config/config.json`, ponha `"ativo": true` em `fontes.extensao`.
2. Confira a ligação:

   ```
   python -m src.main --testar-extensao
   ```

   Com o comando rodando, abra (ou recarregue) uma página de torneio da
   Novibet no Chrome. Em alguns segundos ele mostra quantas odds chegaram.
3. Para rodar o bot: `python -m src.main`. Deixe as abas dos torneios abertas.
   As páginas de torneio ficam no `config.json` (`novibet.caminho`).

## Quando algo não funciona

- **O ícone da extensão mostra `off`**: o bot não está rodando, ou está numa
  porta diferente. A porta fica em três lugares, que precisam ser iguais:
  `fontes.extensao.porta` no `config.json`, `ENDERECO_DO_BOT` no `fundo.js` e
  `host_permissions` no `manifest.json`.
- **O bot diz que a casa está bloqueando**: a aba está mostrando tela de
  verificação. Olhe a aba. Se a tela não passar normalmente, pare por aí.
- **O monitor de saúde avisa que a fonte está sem odds**: a aba foi fechada,
  o computador dormiu ou a Novibet mudou o site. Recarregue a aba. Se
  continuar, o formato pode ter mudado e o parser precisa de ajuste.

## Aviso

Os termos de uso das casas costumam proibir coleta automatizada. Leia a seção
6 de [docs/projeto.md](../docs/projeto.md) antes de deixar isso rodando.
