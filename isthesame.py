import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from difflib import SequenceMatcher
from itertools import zip_longest
from typing import Optional

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter


class LineNumbers(tk.Canvas):
    def __init__(self, master, text_widget: tk.Text, **kwargs):
        super().__init__(master, highlightthickness=0, **kwargs)
        self.text = text_widget
    
    def reset(self):
        self.delete("all")

    def redraw(self):
        self.delete("all")

        # Primeiro índice visível no topo
        index = self.text.index("@0,0")

        while True:
            d = self.text.dlineinfo(index)
            if d is None:
                break

            x, y, w, h, baseline = d
            line = index.split(".")[0]

            # número da linha
            if int(line) < 10:
                self.create_text(20, y, anchor="nw", text=line, fill="#a0a0a0", font=("Arial", 10))
            elif int(line) < 100:
                self.create_text(16, y, anchor="nw", text=line, fill="#a0a0a0", font=("Arial", 10))
            elif int(line) < 1000:
                self.create_text(12, y, anchor="nw", text=line, fill="#a0a0a0", font=("Arial", 10))
            elif int(line) < 10000:
                self.create_text(8, y, anchor="nw", text=line, fill="#a0a0a0", font=("Arial", 10))
            else:
                self.create_text(4, y, anchor="nw", text=line, fill="#a0a0a0", font=("Arial", 10))

            # linha guia horizontal (alinhada com a altura real do Text)
            self.create_line(0, y + h, self.winfo_width(), y + h, fill="#e0e0e0")

            # próxima linha lógica
            index = self.text.index(f"{index}+1line")

class TextComparator:
    def __init__(self, root):
        self.root = root
        self.root.title("Ferramenta de comparação de arquivos de texto")
        self.root.geometry("1600x800")
        self.root.configure(bg="#f0f0f0")

        self._applying_tags = False
        self._syncing_scroll = False
        self._diff_job = None

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.X, side="top")

        main_label = ttk.Label(main_frame, text="Comparador de Arquivos de Texto", font=("Arial", 16))
        main_label.pack(pady=10)

        ttk.Button(main_frame, text="Carregar Arquivos", command=self.abrir_conteudos).pack(pady=5, side=tk.LEFT)
        ttk.Button(main_frame, text="Copiar", command=self.copiar_conteudo).pack(pady=5, side=tk.LEFT)
        ttk.Button(main_frame, text="Editar", command=self.editar_conteudo).pack(pady=5, side=tk.LEFT)
        ttk.Button(main_frame, text="Salvar", command=self.salvar_conteudo).pack(pady=5, side=tk.LEFT)
        ttk.Button(main_frame, text="Trocar", command=self.inverter_conteudo).pack(pady=5, side=tk.LEFT)
        ttk.Button(main_frame, text="Próximo", command=self.proximo_diferenca).pack(pady=5, side=tk.LEFT)
        ttk.Button(main_frame, text="Anterior", command=self.anterior_diferenca).pack(pady=5, side=tk.LEFT)
        ttk.Button(main_frame, text="Apagar2", command=lambda: self.apagar(self.texto_direito)).pack(pady=5, padx=10, side=tk.RIGHT)
        ttk.Button(main_frame, text="Apagar1", command=lambda: self.apagar(self.texto_esquerdo)).pack(pady=5, side=tk.RIGHT)

        # ====== Área: linha+texto (esq), linha+texto (dir) + 1 scrollbar ======

        status_bar = ttk.Frame(root, height=20, relief=tk.SUNKEN, borderwidth=1)
        status_bar.pack(fill=tk.X, side="top")

        # use grid para alinhar corretamente esquerda/direita
        status_bar.grid_columnconfigure(0, weight=2)
        status_bar.grid_columnconfigure(1, weight=1)
        status_bar.grid_columnconfigure(2, weight=2)

        self.nome_primeiro_texto = ttk.Label(status_bar, text="Texto Esquerdo", font=("Arial", 12))
        self.nome_primeiro_texto.grid(row=0, column=0, sticky="w", padx=10)

        self.nome_segundo_texto = ttk.Label(status_bar, text="Texto Direito", font=("Arial", 12))
        self.nome_segundo_texto.grid(row=0, column=2, sticky="e", padx=10)

        self.equality_ratio = ttk.Label(status_bar, text="Igualdade: ", font=("Arial", 12))
        self.equality_ratio.grid(row=0, column=1, sticky="")

        editors = ttk.Frame(root)
        editors.pack(fill=tk.BOTH, expand=True)

        # Textos
        self.texto_esquerdo = tk.Text(editors, wrap=tk.WORD, font=("Arial", 12),
                                      bg="#ffffff", fg="#000000", width=75)
        self.texto_direito = tk.Text(editors, wrap=tk.WORD, font=("Arial", 12),
                                     bg="#ffffff", fg="#000000", width=75)

        # Line numbers (canvas colado no Text => sem offset)
        self.linenos_esq = LineNumbers(editors, self.texto_esquerdo, width=45, bg="#f0f0f0")
        self.linenos_dir = LineNumbers(editors, self.texto_direito, width=45, bg="#f0f0f0")

        # Scrollbar única
        self.scroll = ttk.Scrollbar(editors, orient="vertical", command=self.on_scrollbar)

        # Layout com grid (sem padx grande pra não criar “offset visual”)
        editors.grid_columnconfigure(1, weight=1)
        editors.grid_columnconfigure(3, weight=1)
        editors.grid_rowconfigure(0, weight=1)

        self.linenos_esq.grid(row=0, column=0, sticky="ns")
        self.texto_esquerdo.grid(row=0, column=1, sticky="nsew")

        self.linenos_dir.grid(row=0, column=2, sticky="ns")
        self.texto_direito.grid(row=0, column=3, sticky="nsew")

        self.scroll.grid(row=0, column=4, sticky="ns")

        # Tags em AMBOS os widgets
        self._configure_tags(self.texto_esquerdo)
        self._configure_tags(self.texto_direito)

        # yscrollcommand: quando um rolar, sincroniza o outro + redesenha números
        self.texto_esquerdo["yscrollcommand"] = self.on_textscroll
        self.texto_direito["yscrollcommand"] = self.on_textscroll

        # Redesenhar números quando o conteúdo / tamanho muda
        for w in (self.texto_esquerdo, self.texto_direito):
            w.bind("<KeyRelease>", self._redraw_all_line_numbers)
            w.bind("<ButtonRelease-1>", self._redraw_all_line_numbers)
            w.bind("<Configure>", self._redraw_all_line_numbers)

            # mousewheel: rola os dois como uma página
            w.bind("<MouseWheel>", self._on_mousewheel_windows)

        self.linenos_esq.bind("<Configure>", self._redraw_all_line_numbers)
        self.linenos_dir.bind("<Configure>", self._redraw_all_line_numbers)

        self.texto_esquerdo.bind("<<Modified>>", self.on_text_modified)
        self.texto_direito.bind("<<Modified>>", self.on_text_modified)

        self._redraw_all_line_numbers()

    def define_ratio(self, left: str, right: str):
        ratio = SequenceMatcher(None, left, right).ratio()
        self.equality_ratio.config(text=f"Igualdade: {ratio:.2%}", font=("Arial", 9))

    def _redraw_all_line_numbers(self, event=None):
        self.linenos_esq.redraw()
        self.linenos_dir.redraw()
        
    def reset_lines(self):
        self.linenos_esq.reset()
        self.linenos_dir.reset()

    def _on_mousewheel_windows(self, event):
        # Windows: event.delta geralmente é múltiplo de 120
        units = -1 if event.delta > 0 else 1
        self.texto_esquerdo.yview_scroll(units, "units")
        self.texto_direito.yview_scroll(units, "units")
        self._redraw_all_line_numbers()
        return "break"

    def on_scrollbar(self, *args):
        # Scrollbar única controlando ambos os Text
        self.texto_esquerdo.yview(*args)
        self.texto_direito.yview(*args)
        self._redraw_all_line_numbers()

    def on_textscroll(self, *args):
        # Evita ping-pong de callbacks
        if self._syncing_scroll:
            self.scroll.set(*args)
            return

        self._syncing_scroll = True
        try:
            self.scroll.set(*args)

            # move o outro Text para o mesmo "fraction"
            self.texto_esquerdo.yview_moveto(args[0])
            self.texto_direito.yview_moveto(args[0])

            self._redraw_all_line_numbers()
        finally:
            self._syncing_scroll = False

    def _configure_tags(self, w: tk.Text):
        w.tag_config("delete", background="#ffe3e3", foreground="#ff0000")
        w.tag_config("insert", background="#ffe3e3", foreground="#22683a")
        w.tag_config("replace", background="#ffdea1", foreground="#e6ad32")
        w.tag_config("missing", background="#3a3a3a", foreground="#e6e6e6")
        # Opcional (útil para depurar/estender):
        # w.tag_config("equal")

        w.tag_raise("delete")
        w.tag_raise("insert")
        w.tag_raise("replace")
        w.tag_raise("missing")

    def _normalize_text(self, s: str) -> str:
        return s.replace("\r\n", "\n").replace("\r", "\n")

    def on_text_modified(self, event):
        if self._applying_tags:
            event.widget.edit_modified(False)
            return

        if not event.widget.edit_modified():
            return

        # Salva estado do cursor/scroll ANTES de re-renderizar
        src = event.widget
        left_insert = self.texto_esquerdo.index("insert")
        right_insert = self.texto_direito.index("insert")
        yfrac = self.texto_esquerdo.yview()[0]  # como o scroll é sincronizado, 1 fração basta

        # Reseta flag de modificado agora (a próxima tecla vai setar de novo)
        src.edit_modified(False)

        # Debounce: cancela job anterior e agenda um novo
        if self._diff_job is not None:
            try:
                self.root.after_cancel(self._diff_job)
            except Exception:
                pass
            self._diff_job = None

        def _run():
            self._diff_job = None

            left = self._normalize_text(self.texto_esquerdo.get("1.0", "end-1c"))
            right = self._normalize_text(self.texto_direito.get("1.0", "end-1c"))

            # Define ratio
            self.define_ratio(left, right)
    
            self._applying_tags = True
            try:
                grade = self.diff_to_grade(left, right)
                self.render_grade(grade)
            finally:
                self._applying_tags = False

            # Restaura scroll
            try:
                self.texto_esquerdo.yview_moveto(yfrac)
                self.texto_direito.yview_moveto(yfrac)
            except Exception:
                pass

            # Restaura cursor no widget que estava sendo editado
            try:
                if src is self.texto_esquerdo:
                    self.texto_esquerdo.mark_set("insert", left_insert)
                    self.texto_esquerdo.see("insert")
                else:
                    self.texto_direito.mark_set("insert", right_insert)
                    self.texto_direito.see("insert")
            except Exception:
                pass

            self.texto_esquerdo.edit_modified(False)
            self.texto_direito.edit_modified(False)
            self._redraw_all_line_numbers()

        self._diff_job = self.root.after(200, _run)

# ==== INÍCIO FUNÇÕES DOS BOTÕES ==== #

    def copiar_conteudo(self):
        pass

    def editar_conteudo(self):
        pass

    def salvar_conteudo(self):
        c = canvas.Canvas("output.pdf", pagesize=letter)
        c.drawString(100, 750, "Conteúdo do Texto Esquerdo:")
        texto_esquerdo_content = self.texto_esquerdo.get("1.0", "end-1c")
        textobject = c.beginText(100, 730)
        for line in texto_esquerdo_content.splitlines():
            textobject.textLine(line)
        c.drawText(textobject)
        c.save()

    def inverter_conteudo(self):
        self.texto_direito_content = self._normalize_text(self.texto_direito.get("1.0", "end-1c"))
        self.texto_esquerdo_content = self._normalize_text(self.texto_esquerdo.get("1.0", "end-1c"))
        self.texto_esquerdo.delete("1.0", tk.END)
        self.texto_direito.delete("1.0", tk.END)
        self.texto_esquerdo.insert(tk.END, self.texto_direito_content)
        self.texto_direito.insert(tk.END, self.texto_esquerdo_content)
        self._redraw_all_line_numbers()

    def proximo_diferenca(self):
        pass

    def anterior_diferenca(self):
        pass
    
    def apagar(self, texto):
        texto.delete("1.0", tk.END)
        self.reset_lines()

# === FIM FUNÇÕES DOS BOTÕES === #

    def _line_to_display(self, line: Optional[str]) -> str:
        """Garante que cada linha renderizada ocupe exatamente 1 linha visual."""
        if line is None:
            return "" # Outro lado
        if line.endswith("\n"):
            return line[:-1]
        return line

    def _split_body_nl(self, line: str):
        if line.endswith("\n"):
            return line[:-1], "\n"
        return line, ""

    def char_diff_tokens(self, a, b):
        matcher = SequenceMatcher(None, a, b)
        tokens_a, tokens_b = [], []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                tokens_a.append(("equal", a[i1:i2]))
                tokens_b.append(("equal", b[j1:j2]))
            elif tag == "replace":
                tokens_a.append(("replace", a[i1:i2]))
                tokens_b.append(("replace", b[j1:j2]))
            elif tag == "delete":
                tokens_a.append(("delete", a[i1:i2]))
            elif tag == "insert":
                tokens_b.append(("insert", b[j1:j2]))

        return tokens_a, tokens_b

    def diff_to_grade(self, text1: str, text2: str):
        """Opção B: gera uma grade alinhada para renderizar diretamente nos Text."""
        lines1 = text1.splitlines(True)
        lines2 = text2.splitlines(True)

        matcher = SequenceMatcher(None, lines1, lines2)

        # cada item: (segments_left, segments_right)
        # segments: [(tag_or_None, text)]
        grade = []

        def plain(s: str):
            return [(None, s)] if s else []

        def tagged(tag_name: str, s: str):
            return [(tag_name, s)] if s else []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for a_line, b_line in zip(lines1[i1:i2], lines2[j1:j2]):
                    grade.append((plain(self._line_to_display(a_line)),
                                  plain(self._line_to_display(b_line))))

            elif tag == "delete":
                for a_line in lines1[i1:i2]:
                    grade.append((tagged("delete", self._line_to_display(a_line)),
                                  tagged("missing", self._line_to_display(None))))

            elif tag == "insert":
                for b_line in lines2[j1:j2]:
                    grade.append((tagged("missing", self._line_to_display(None)),
                                  tagged("insert", self._line_to_display(b_line))))

            elif tag == "replace":
                block1 = lines1[i1:i2]
                block2 = lines2[j1:j2]

                for a_line, b_line in zip_longest(block1, block2, fillvalue=None):
                    if a_line is None:
                        grade.append((tagged("missing", self._line_to_display(None)),
                                      tagged("insert", self._line_to_display(b_line))))
                        continue
                    if b_line is None:
                        grade.append((tagged("delete", self._line_to_display(a_line)),
                                      tagged("missing", self._line_to_display(None))))
                        continue

                    a_body, _ = self._split_body_nl(a_line)
                    b_body, _ = self._split_body_nl(b_line)
                    ta, tb = self.char_diff_tokens(a_body, b_body)

                    seg_left = []
                    for t, s in ta:
                        seg_left.extend(plain(s) if t == "equal" else tagged(t, s))

                    seg_right = []
                    for t, s in tb:
                        seg_right.extend(plain(s) if t == "equal" else tagged(t, s))

                    grade.append((seg_left, seg_right))

        return grade

    def render_grade(self, grade):
        # renderiza os DOIS lados em lockstep
        self.texto_esquerdo.delete("1.0", "end")
        self.texto_direito.delete("1.0", "end")

        def insert_segments(widget: tk.Text, segments):
            for tag, text in segments:
                if not text:
                    continue
                if tag is None:
                    widget.insert("end", text)
                else:
                    widget.insert("end", text, tag)

        def has_visible_text(segments) -> bool:
            return any(bool(text) for _, text in segments)

        for idx, (seg_left, seg_right) in enumerate(grade):
            insert_segments(self.texto_esquerdo, seg_left)
            insert_segments(self.texto_direito, seg_right)

            # quebra de linha SOMENTE entre linhas (evita criar “linha extra” no final)
            if idx < len(grade) - 1:
                self.texto_esquerdo.insert("end", "\n")
                self.texto_direito.insert("end", "\n")

        if grade:
            last_left, last_right = grade[-1]
            if (not has_visible_text(last_left)) and (not has_visible_text(last_right)):
                self.texto_esquerdo.insert("end", "\n")
                self.texto_direito.insert("end", "\n")


    def abrir_conteudos(self):
        file1_path = filedialog.askopenfilename(
            title="Selecione o texto esquerdo",
            filetypes=[("All Files", "*.*"), ("XML Files", "*.xml"),("Text Files", "*.txt")]
        )
        file2_path = filedialog.askopenfilename(
            title="Selecione o texto direito",
            filetypes=[("All Files", "*.*"), ("XML Files", "*.xml"),("Text Files", "*.txt")]
        )

        if file1_path and file2_path:
            try:
                with open(file1_path, "r", encoding="utf-8") as f1:
                    conteudo1 = self._normalize_text(f1.read())
                with open(file2_path, "r", encoding="utf-8") as f2:
                    conteudo2 = self._normalize_text(f2.read())

                # Evita que o <<Modified>> dispare no meio do carregamento/render.
                self._applying_tags = True
                try:
                    grade = self.diff_to_grade(conteudo1, conteudo2)
                    self.render_grade(grade)
                finally:
                    self._applying_tags = False

                self.define_ratio(conteudo1, conteudo2)

                self.texto_esquerdo.edit_modified(False)
                self.texto_direito.edit_modified(False)
                
                nome_texto1 = file1_path.split("/")[-1]
                nome_texto2 = file2_path.split("/")[-1]
            
                self.nome_primeiro_texto.config(text=nome_texto1, font=("Arial", 9))
                self.nome_segundo_texto.config(text=nome_texto2, font=("Arial", 9))

                self._redraw_all_line_numbers()

            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível abrir os arquivos: {e}")
        else:
            messagebox.showwarning("Aviso", "Você deve selecionar dois arquivos de texto.")

def main():
    root = tk.Tk()
    app = TextComparator(root)
    root.mainloop()


if __name__ == "__main__":
    main()