import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

type UserRole = 'pharmacy' | 'supplier';

export type AuthUser = {
  id: string;
  name: string;
  phone: string;
  address: string;
};

type AuthState = {
  token: string | null;
  role: UserRole | null;
  user: AuthUser | null;
  loading: boolean;
  signIn: (token: string, role: UserRole, user: AuthUser) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

const KEY = 'pharmacy_auth_v1';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [role, setRole] = useState<UserRole | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          setToken(parsed.token);
          setRole(parsed.role);
          setUser(parsed.user);
        }
      } catch {}
      setLoading(false);
    })();
  }, []);

  const signIn = async (t: string, r: UserRole, u: AuthUser) => {
    await AsyncStorage.setItem(KEY, JSON.stringify({ token: t, role: r, user: u }));
    setToken(t);
    setRole(r);
    setUser(u);
  };

  const signOut = async () => {
    await AsyncStorage.removeItem(KEY);
    setToken(null);
    setRole(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ token, role, user, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

export async function apiFetch<T = any>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${BACKEND_URL}/api${path}`, { ...options, headers });
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const msg = (data && data.detail) || `خطأ ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : 'خطأ');
  }
  return data as T;
}
