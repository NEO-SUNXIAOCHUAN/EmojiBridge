// Thin GUI entrypoint. The desktop process owns its own Windows Job and data.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
[assembly: AssemblyTitle("EmojiBridge")]
[assembly: AssemblyProduct("EmojiBridge")]
[assembly: AssemblyDescription("EmojiBridge Windows 桌面启动入口")]
[assembly: AssemblyVersion("0.152.0.0")]
[assembly: AssemblyFileVersion("0.152.0.0")]
internal static class Launcher {
    // CommandLineToArgvW/CRT quoting, including quotes and trailing backslashes.
    internal static string Quote(string value) {
        var result=new StringBuilder("\""); int slashes=0;
        foreach(char c in value) {
            if(c=='\\'){slashes++;continue;}
            if(c=='"'){result.Append('\\',slashes*2+1);result.Append(c);slashes=0;continue;}
            result.Append('\\',slashes);slashes=0;result.Append(c);
        }
        result.Append('\\',slashes*2);return result.Append('"').ToString();
    }
    [STAThread] private static int Main(string[] args) {
        try {
            string root=AppDomain.CurrentDomain.BaseDirectory;
            string python=Path.Combine(root,"runtime","pythonw.exe");
            string script=Path.Combine(root,"scripts","desktop_modern.py");
            foreach(string path in new[]{python,script,Path.Combine(root,"runtime","python312.dll"),Path.Combine(root,"runtime","desktop","webview","__init__.py")})
                if(!File.Exists(path))throw new FileNotFoundException("程序组件缺失，请完整解压整个 ZIP 后再运行。缺少："+Path.GetFileName(path));
            var command=new StringBuilder("-X utf8 "+Quote(script));
            foreach(string arg in args)command.Append(" ").Append(Quote(arg));
            var start=new ProcessStartInfo(python,command.ToString());
            start.WorkingDirectory=root;start.UseShellExecute=false;start.CreateNoWindow=true;
            Process child=Process.Start(start);
            // Dispose only our process handle. Do not terminate the application.
            child.Dispose();return 0;
        } catch(Exception error) {
            MessageBox.Show(error.Message,"EmojiBridge 未能启动",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;
        }
    }
}
