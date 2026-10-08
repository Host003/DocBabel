import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import {
  FileText,
  Upload,
  Archive,
  BookOpen,
  Cpu,
  Shield,
  LogOut,
  Menu,
  X,
  UserRoundCog,
} from 'lucide-react';
import { useState } from 'react';
import { useAuth } from '../use-auth';
import { authApi } from '../api';

const navItems = [
  { to: '/', icon: Upload, label: '翻译' },
  { to: '/files', icon: Archive, label: '文件库' },
  { to: '/tasks', icon: FileText, label: '任务' },
  { to: '/glossaries', icon: BookOpen, label: '术语表' },
  { to: '/models', icon: Cpu, label: '模型' },
];

export default function Layout() {
  const { user, logout, isAdmin, updateUser } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      isActive
        ? 'bg-blue-50 text-blue-700'
        : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
    }`;

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-gray-200 bg-white transition-transform lg:static lg:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex h-16 items-center gap-2 border-b border-gray-200 px-6">
          <FileText className="h-6 w-6 text-blue-600" />
          <span className="text-lg font-bold text-gray-900">BabelDOC</span>
        </div>

        <nav className="flex-1 space-y-1 p-4">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} className={linkClass} onClick={() => setSidebarOpen(false)}>
              <item.icon className="h-5 w-5" />
              {item.label}
            </NavLink>
          ))}
          {isAdmin && (
            <NavLink to="/admin" className={linkClass} onClick={() => setSidebarOpen(false)}>
              <Shield className="h-5 w-5" />
              管理
            </NavLink>
          )}
        </nav>

        <div className="border-t border-gray-200 p-4">
          <button
            onClick={() => setSettingsOpen(true)}
            className="mb-3 flex w-full items-center gap-3 rounded-lg px-4 py-2 text-left transition-colors hover:bg-gray-100"
            title="账号设置"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-600">
              <span className="text-sm font-semibold">{user?.username?.[0]?.toUpperCase() || 'U'}</span>
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-gray-900">{user?.username}</p>
              <p className="truncate text-xs text-gray-500">{user?.email}</p>
            </div>
            <UserRoundCog className="ml-auto h-4 w-4 text-gray-400" />
          </button>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-3 rounded-lg px-4 py-2.5 text-sm font-medium text-gray-600 transition-colors hover:bg-red-50 hover:text-red-600"
          >
            <LogOut className="h-5 w-5" />
            退出登录
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-16 items-center border-b border-gray-200 bg-white px-6 lg:hidden">
          <button onClick={() => setSidebarOpen(true)} className="text-gray-600">
            {sidebarOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
          <span className="ml-4 text-lg font-bold text-gray-900">BabelDOC</span>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>

      {settingsOpen && user && (
        <AccountSettingsModal
          user={user}
          updateUser={updateUser}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}

interface AccountSettingsModalProps {
  user: { username: string; email: string };
  updateUser: (patch: { email?: string }) => void;
  onClose: () => void;
}

function AccountSettingsModal({ user, updateUser, onClose }: AccountSettingsModalProps) {
  const [tab, setTab] = useState<'email' | 'password'>('email');

  // Email tab state
  const [email, setEmail] = useState(user.email);
  const [emailCurrentPwd, setEmailCurrentPwd] = useState('');
  const [emailLoading, setEmailLoading] = useState(false);
  const [emailError, setEmailError] = useState('');
  const [emailOk, setEmailOk] = useState(false);

  // Password tab state
  const [curPwd, setCurPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [pwdLoading, setPwdLoading] = useState(false);
  const [pwdError, setPwdError] = useState('');
  const [pwdOk, setPwdOk] = useState(false);

  const handleEmail = async () => {
    setEmailError(''); setEmailOk(false);
    if (!emailCurrentPwd) { setEmailError('请填写当前密码'); return; }
    if (email === user.email) { setEmailError('邮箱未变化'); return; }
    setEmailLoading(true);
    try {
      const res = await authApi.changeEmail(email.trim(), emailCurrentPwd);
      updateUser({ email: res.data.email });
      setEmailOk(true);
      setEmailCurrentPwd('');
    } catch (err: unknown) {
      setEmailError((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || '修改失败');
    } finally {
      setEmailLoading(false);
    }
  };

  const handlePassword = async () => {
    setPwdError(''); setPwdOk(false);
    if (!curPwd) { setPwdError('请填写当前密码'); return; }
    if (newPwd.length < 6) { setPwdError('新密码至少 6 位'); return; }
    if (newPwd !== confirmPwd) { setPwdError('两次输入的新密码不一致'); return; }
    setPwdLoading(true);
    try {
      await authApi.changePassword(curPwd, newPwd);
      setPwdOk(true);
      setCurPwd(''); setNewPwd(''); setConfirmPwd('');
    } catch (err: unknown) {
      setPwdError((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || '修改失败');
    } finally {
      setPwdLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="mx-4 w-full max-w-md rounded-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">账号设置</h2>
            <p className="text-xs text-gray-500">{user.username} · {user.email}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>

        <div className="flex gap-1 border-b border-gray-100 px-6 pt-2">
          {(['email', 'password'] as const).map((t) => (
            <button
              key={t}
              onClick={() => { setTab(t); setEmailOk(false); setPwdOk(false); setEmailError(''); setPwdError(''); }}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {t === 'email' ? '修改邮箱' : '修改密码'}
            </button>
          ))}
        </div>

        <div className="px-6 py-4 space-y-4">
          {tab === 'email' && (
            <>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">新邮箱地址</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">当前密码</label>
                <input
                  type="password"
                  value={emailCurrentPwd}
                  onChange={(e) => setEmailCurrentPwd(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  placeholder="用于验证本人操作"
                />
              </div>
              {emailError && <p className="text-sm text-red-500">{emailError}</p>}
              {emailOk && <p className="text-sm text-green-600">邮箱已更新</p>}
            </>
          )}

          {tab === 'password' && (
            <>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">当前密码</label>
                <input
                  type="password"
                  value={curPwd}
                  onChange={(e) => setCurPwd(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">新密码（至少 6 位）</label>
                <input
                  type="password"
                  value={newPwd}
                  onChange={(e) => setNewPwd(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">确认新密码</label>
                <input
                  type="password"
                  value={confirmPwd}
                  onChange={(e) => setConfirmPwd(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              {pwdError && <p className="text-sm text-red-500">{pwdError}</p>}
              {pwdOk && <p className="text-sm text-green-600">密码已更新</p>}
            </>
          )}
        </div>

        <div className="flex justify-end gap-3 border-t border-gray-100 px-6 py-4">
          <button onClick={onClose} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">关闭</button>
          {tab === 'email' ? (
            <button onClick={handleEmail} disabled={emailLoading} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {emailLoading ? '提交中...' : '保存邮箱'}
            </button>
          ) : (
            <button onClick={handlePassword} disabled={pwdLoading} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {pwdLoading ? '提交中...' : '修改密码'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
