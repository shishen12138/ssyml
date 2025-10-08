from tkinterdnd2 import DND_FILES, TkinterDnD
import tkinter as tk
from tkinter import messagebox
import pyperclip
import os

class CompareApp:
    def __init__(self, root):
        self.root = root
        self.root.title("IP 对比工具（导入去重并显示导入重复）")

        frame = tk.Frame(root)
        frame.pack(padx=10, pady=10, fill="x")

        tk.Label(frame, text="输入框1").grid(row=0, column=0)
        self.text1 = tk.Text(frame, width=40, height=10)
        self.text1.grid(row=1, column=0, padx=5)
        self.text1.drop_target_register(DND_FILES)
        self.text1.dnd_bind('<<Drop>>', lambda e: self.on_drop(e, self.text1, self.list_left_dup))

        tk.Label(frame, text="输入框2").grid(row=0, column=1)
        self.text2 = tk.Text(frame, width=40, height=10)
        self.text2.grid(row=1, column=1, padx=5)
        self.text2.drop_target_register(DND_FILES)
        self.text2.dnd_bind('<<Drop>>', lambda e: self.on_drop(e, self.text2, self.list_right_dup))

        tk.Button(root, text="对比", command=self.compare, bg="lightblue").pack(pady=5)

        # 四个列表框
        list_frame = tk.Frame(root)
        list_frame.pack(padx=10, pady=10, fill="both", expand=True)

        self.list_left_unique = self.create_list(list_frame, "左边独有")
        self.list_left_dup = self.create_list(list_frame, "左边导入重复")
        self.list_right_dup = self.create_list(list_frame, "右边导入重复")
        self.list_right_unique = self.create_list(list_frame, "右边独有")

    def create_list(self, parent, title):
        frame = tk.Frame(parent)
        frame.pack(side="left", fill="both", expand=True, padx=5)
        tk.Label(frame, text=title).pack()
        lb = tk.Listbox(frame)
        lb.pack(fill="both", expand=True)
        lb.bind("<Double-Button-1>", lambda e, l=lb: self.copy_item(l))
        return lb

    def copy_item(self, listbox):
        sel = listbox.curselection()
        if sel:
            value = listbox.get(sel[0])
            pyperclip.copy(value)
            messagebox.showinfo("已复制", f"已复制内容:\n{value}")

    def on_drop(self, event, widget, dup_listbox):
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        file_path = paths[0]
        if os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                seen = set()
                unique_lines = []
                duplicates = []
                for line in lines:
                    if line not in seen:
                        seen.add(line)
                        unique_lines.append(line)
                    else:
                        duplicates.append(line)

                # 更新文本框内容
                widget.delete("1.0", tk.END)
                widget.insert(tk.END, "\n".join(unique_lines))

                # 更新导入重复列表框
                dup_listbox.delete(0, tk.END)
                for d in duplicates:
                    dup_listbox.insert(tk.END, d)

                messagebox.showinfo(
                    "导入完成",
                    f"文件 {os.path.basename(file_path)} 已导入。\n"
                    f"有效行（去重后）: {len(unique_lines)}\n导入重复行: {len(duplicates)}"
                )

            except Exception as e:
                messagebox.showerror("错误", f"无法读取文件: {e}")

    def compare(self):
        # 清空独有列表框
        self.list_left_unique.delete(0, tk.END)
        self.list_right_unique.delete(0, tk.END)

        lines1 = set(line.strip() for line in self.text1.get("1.0", tk.END).splitlines() if line.strip())
        lines2 = set(line.strip() for line in self.text2.get("1.0", tk.END).splitlines() if line.strip())

        left_unique = sorted(lines1 - lines2)
        right_unique = sorted(lines2 - lines1)

        for ip in left_unique:
            self.list_left_unique.insert(tk.END, ip)
        for ip in right_unique:
            self.list_right_unique.insert(tk.END, ip)

        messagebox.showinfo(
            "完成",
            f"左边独有: {len(left_unique)}\n"
            f"左边导入重复: {len(self.list_left_dup.get(0, tk.END))}\n"
            f"右边导入重复: {len(self.list_right_dup.get(0, tk.END))}\n"
            f"右边独有: {len(right_unique)}"
        )

if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = CompareApp(root)
    root.mainloop()
