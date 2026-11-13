// QQ's MSAA/IAccessible2 controls, used only when UIA exposes a window shell.
// COM interface ABI: LinuxA11y/IAccessible2 api/Accessible2.idl (IAccessible base).
// No chat text/value enumeration, coordinates, input injection or client settings.
using System;
using System.Collections.Generic;
using System.Collections;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Accessibility;

public sealed class QQAccessibleTree : IDisposable {
    [DllImport("oleacc.dll")]
    static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint id, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out IAccessible result);
    [DllImport("oleacc.dll")]
    static extern int AccessibleChildren(IAccessible parent, int start, int count,
        [Out, MarshalAs(UnmanagedType.LPArray, SizeParamIndex=2)] object[] children, out int obtained);
    [ComImport, Guid("6d5140c1-7436-11ce-8034-00aa006009fa"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IServiceProvider {
        [PreserveSig] int QueryService(ref Guid service, ref Guid iid, out IntPtr result);
    }
    // IUnknown(3), IDispatch(4), IAccessible(21); IA2 begins at slot 28.
    // Only these documented methods are called; every QueryService ref is released.
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int GetString(IntPtr self, [MarshalAs(UnmanagedType.BStr)] out string value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int GetInt(IntPtr self, out int value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int ScrollTo(IntPtr self, int kind);
    static readonly Guid AccessibleId = new Guid("618736e0-3c3d-11cf-810c-00aa00389b71");
    static readonly Guid IA2Id = new Guid("e89f726e-c4f4-4c19-bb19-b647d7fa8478");
    static T Method<T>(IntPtr obj, int slot) where T: class {
        return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj), slot * IntPtr.Size), typeof(T)) as T;
    }
    static IntPtr IA2(IAccessible acc) {
        var service = acc as IServiceProvider;
        if (service == null) return IntPtr.Zero;
        Guid sid = AccessibleId, iid = IA2Id;
        IntPtr result;
        int hr = service.QueryService(ref sid, ref iid, out result);
        if (hr >= 0) return result;
        if (result != IntPtr.Zero) Marshal.Release(result);
        return IntPtr.Zero;
    }
    static string ClassAttribute(IAccessible acc) {
        IntPtr obj = IA2(acc);
        if (obj == IntPtr.Zero) return "";
        try {
            string attributes;
            int hr = Method<GetString>(obj, 45)(obj, out attributes);
            if (hr < 0) Marshal.ThrowExceptionForHR(hr);
            // Read only the class attribute. Never return or log other attributes.
            var match = Regex.Match(attributes ?? "", @"(?:^|;)class:((?:\\.|[^;])*)");
            return match.Success ? Regex.Replace(match.Groups[1].Value, @"\\(.)", "$1") : "";
        } finally { Marshal.Release(obj); }
    }
    public sealed class Node {
        internal IAccessible Acc;
        internal object Child;
        public Node Parent;
        public int Role;
        public string ClassName;
        int? state, uniqueId;
        int[] rect;
        public bool HasClass(string name) {
            return Array.IndexOf(ClassName.Split(new char[]{' ', '\t', '\r', '\n'}, StringSplitOptions.RemoveEmptyEntries), name) >= 0;
        }
        public bool Within(Node ancestor) {
            for (Node p = Parent; p != null; p = p.Parent) if (p == ancestor) return true;
            return false;
        }
        public bool InToolbar {
            get { for (Node p = Parent; p != null; p = p.Parent) if (p.Role == 22) return true; return false; }
        }
        // Caller reads Name only for toolbar buttons or known favorite controls.
        public string Name { get { return Acc.get_accName(Child) ?? ""; } }
        // A tree exists for one request only. Snapshot each property once.
        public int State { get { if (!state.HasValue) state=Convert.ToInt32(Acc.get_accState(Child)); return state.Value; } }
        public bool Visible { get { return (State & (0x8000 | 0x10000)) == 0; } }
        public int[] Rect {
            get { if (rect == null) { int x,y,w,h; Acc.accLocation(out x,out y,out w,out h,Child); rect=new int[]{x,y,x+w,y+h}; } return rect; }
        }
        public int UniqueId {
            get {
                if (uniqueId.HasValue) return uniqueId.Value;
                if (!(Child is int) || (int)Child != 0) throw new InvalidOperationException("qq_msaa_cell_identity_unavailable");
                IntPtr obj = IA2(Acc);
                if (obj == IntPtr.Zero) throw new InvalidOperationException("qq_msaa_cell_identity_unavailable");
                try {
                    int value; int hr = Method<GetInt>(obj, 41)(obj, out value);
                    if (hr < 0) Marshal.ThrowExceptionForHR(hr);
                    if (value == 0) throw new InvalidOperationException("qq_msaa_cell_identity_unavailable");
                    uniqueId=value; return value;
                } finally { Marshal.Release(obj); }
            }
        }
        public void InvokeToolbar() {
            if (Role != 43 || !InToolbar || Name != "表情" || !Visible || (State & 1) != 0)
                throw new InvalidOperationException("qq_msaa_emoji_button_changed");
            Acc.accDoDefaultAction(Child);
        }
        public void SelectFavorites() {
            if (Role != 43 || Name != "我的收藏" || !Visible || (State & 1) != 0)
                throw new InvalidOperationException("qq_msaa_favorite_tab_changed");
            // Called only within the verified panel while its personal grid is absent.
            // A checked/pressed/mixed tab with no grid must settle; never toggle it off.
            if ((State & (8 | 16 | 32)) != 0) throw new InvalidOperationException("qq_uia_tab_state_unconfirmed");
            Acc.accDoDefaultAction(Child);
        }
        public void RevealCell() {
            if (!HasClass("collection-sticker")) throw new InvalidOperationException("qq_uia_cell_changed");
            IntPtr obj = IA2(Acc);
            if (obj == IntPtr.Zero) throw new InvalidOperationException("qq_msaa_scroll_unavailable");
            try {
                // IA2_SCROLL_TYPE_ANYWHERE=6. Reveals a cell, NEVER invokes it.
                int hr = Method<ScrollTo>(obj, 32)(obj, 6);
                if (hr < 0) Marshal.ThrowExceptionForHR(hr);
            } finally { Marshal.Release(obj); }
        }
    }
    public readonly List<Node> Nodes = new List<Node>();
    public Node[] Classes(string name, Node ancestor, bool visible) {
        return Nodes.FindAll(n => n.HasClass(name) && (ancestor==null || n.Within(ancestor)) && (!visible || n.Visible)).ToArray();
    }
    public Node[] Buttons(string name, Node ancestor, bool toolbar, bool visible) {
        return Nodes.FindAll(n => n.Role==43 && (ancestor==null || n.Within(ancestor)) && (!toolbar || n.InToolbar)
            && (!visible || n.Visible) && n.Name==name).ToArray();
    }
    public Hashtable[] Cells(Node grid, long hwnd) {
        var result=new List<Hashtable>();int[] box=grid.Rect;
        foreach(Node n in Classes("collection-sticker",grid,false)) {
            int[] b=n.Rect;
            bool full=n.Visible && b[0]>=box[0] && b[1]>=box[1] && b[2]<=box[2] && b[3]<=box[3] && b[2]>b[0] && b[3]>b[1];
            result.Add(new Hashtable{{"rect",b},{"fully_visible",full},{"runtime_id",new long[]{-161,hwnd,n.UniqueId}}});
        }
        return result.ToArray();
    }
    readonly HashSet<IAccessible> owned = new HashSet<IAccessible>();
    public QQAccessibleTree(long hwnd) {
        try {
            Guid iid = AccessibleId; IAccessible root;
            int hr = AccessibleObjectFromWindow(new IntPtr(hwnd), 0xfffffffc, ref iid, out root);
            if (hr < 0) Marshal.ThrowExceptionForHR(hr);
            if (root == null) throw new InvalidOperationException("qq_msaa_root_missing");
            owned.Add(root);
            var queue = new Queue<Node>(); queue.Enqueue(new Node{Acc=root, Child=0});
            var watch = Stopwatch.StartNew();
            while (queue.Count > 0) {
                if (Nodes.Count + queue.Count > 4096 || watch.Elapsed.TotalSeconds > 5)
                    throw new InvalidOperationException("qq_msaa_tree_limit");
                Node n = queue.Dequeue(); Nodes.Add(n);
                n.Role = Convert.ToInt32(n.Acc.get_accRole(n.Child));
                bool self = n.Child is int && (int)n.Child == 0;
                // Graphic/text/composer leaves cannot contain our controls.
                if (n.Role == 40 || n.Role == 41 || n.Role == 42) { n.ClassName=""; continue; }
                n.ClassName = self ? ClassAttribute(n.Acc) : "";
                if (!self) continue;
                // Never inspect a sticker's image or a button's icon/text.
                if (n.Role == 43 || n.HasClass("collection-sticker") || n.HasClass("sticker-list__import")) continue;
                int count = n.Acc.accChildCount;
                if (count < 0 || count + Nodes.Count + queue.Count > 4096)
                    throw new InvalidOperationException("qq_msaa_tree_limit");
                if (count == 0) continue;
                object[] children = new object[count]; int obtained;
                hr = AccessibleChildren(n.Acc, 0, count, children, out obtained);
                // Own every returned object even on a partial/failing enumeration.
                var added = new HashSet<IAccessible>();
                foreach (object child in children) {
                    var acc = child as IAccessible;
                    if (acc != null && owned.Add(acc)) added.Add(acc);
                }
                if (hr < 0) Marshal.ThrowExceptionForHR(hr);
                if (obtained != count) throw new InvalidOperationException("qq_msaa_tree_changed");
                foreach (object child in children) {
                    var acc = child as IAccessible;
                    if (acc != null && added.Remove(acc)) queue.Enqueue(new Node{Acc=acc, Child=0, Parent=n});
                    else if (child is int && (int)child > 0) queue.Enqueue(new Node{Acc=n.Acc, Child=child, Parent=n});
                }
            }
        } catch { Dispose(); throw; }
    }
    public void Dispose() {
        foreach (var acc in owned) {
            if (Marshal.IsComObject(acc)) Marshal.FinalReleaseComObject(acc);
        }
        owned.Clear(); Nodes.Clear();
    }
}
