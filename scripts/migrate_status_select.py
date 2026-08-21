"""Migração única: troca o checkbox "Recebido" por um <select> de status
(pendente / recebido / nao_compareceu / reagendado) em cada carga do index.html.

Roda uma vez, localmente. Não faz parte do deploy.
"""
import re
import sys
from pathlib import Path

INDEX_PATH = Path(__file__).resolve().parent.parent / "index.html"

CELL_RE = re.compile(
    r'<td class="col-recebido">(?P<body>.*?)</td>',
    re.DOTALL,
)

INPUT_RE = re.compile(
    r'<input type="checkbox" class="chk-recebido"\s*(?P<checked>checked)?\s*'
    r'data-id="(?P<id>[^"]*)" data-initial="(?P<initial>[01])"\s*'
    r'data-cd="(?P<cd>[^"]*)" data-data="(?P<data>[^"]*)"\s*'
    r'data-forn="(?P<forn>[^"]*)" data-carga="(?P<carga>[^"]*)"\s*'
    r'onchange="onToggleRecebido\(this\)">',
    re.DOTALL,
)

NOTA_RE = re.compile(r'<div class="confirm-nota">.*?</div>', re.DOTALL)

OPTIONS = [
    ("pendente", "Pendente"),
    ("recebido", "Recebido"),
    ("nao_compareceu", "Não compareceu"),
    ("reagendado", "Reagendado"),
]


def build_select(attrs, status, nota_html):
    opts = []
    for value, label in OPTIONS:
        sel = " selected" if value == status else ""
        opts.append(f'              <option value="{value}"{sel}>{label}</option>')
    opts_html = "\n".join(opts)
    nota_block = f"\n            {nota_html}" if nota_html else ""
    return (
        '<td class="col-recebido">\n'
        f'            <select class="status-select status-{status}" data-id="{attrs["id"]}"'
        f' data-status-initial="{status}" data-status-atual="{status}"\n'
        f'              data-cd="{attrs["cd"]}" data-data="{attrs["data"]}"\n'
        f'              data-forn="{attrs["forn"]}" data-carga="{attrs["carga"]}"\n'
        '              onchange="onStatusChange(this)">\n'
        f'{opts_html}\n'
        '            </select>'
        f'{nota_block}\n'
        '          </td>'
    )


def migrate_cell(match):
    body = match.group("body")
    m = INPUT_RE.search(body)
    if not m:
        raise ValueError(f"Não encontrei o checkbox esperado dentro de: {body[:200]!r}")
    status = "recebido" if (m.group("checked") or m.group("initial") == "1") else "pendente"
    nota_match = NOTA_RE.search(body)
    nota_html = nota_match.group(0) if nota_match else ""
    return build_select(m.groupdict(), status, nota_html)


def main():
    text = INDEX_PATH.read_text(encoding="utf-8")
    # Só migra o HTML estático (fora do <script>) — o template JS de
    # renderTabelaDiaJS é ajustado à mão, não por esta regex.
    script_idx = text.index("<script>")
    head, tail = text[:script_idx], text[script_idx:]
    new_head, count = CELL_RE.subn(migrate_cell, head)
    print(f"{count} célula(s) col-recebido migradas.")
    if count == 0:
        print("Nada para migrar (já migrado?). Abortando sem escrever.")
        return
    INDEX_PATH.write_text(new_head + tail, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
