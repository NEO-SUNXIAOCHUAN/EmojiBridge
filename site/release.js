(() => {
  const buttons = document.querySelectorAll('.edition-link');
  if (!buttons.length) return;
  buttons.forEach(button => button.addEventListener('click', () => {
    const hint = document.querySelector('#download-followup');
    if (hint) {
      hint.hidden = false;
      hint.textContent = '全部解压到新文件夹，双击 EB/EmojiBridge.exe。好用的话，欢迎在 GitHub 点个 Star。';
    }
  }));
})();
