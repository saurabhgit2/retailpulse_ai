import { createContext } from 'react';

// Kept in its own file so that component files export only components
// (this keeps Vite's hot reload reliable). The provider is in AuthProvider.jsx.
export const AuthContext = createContext(null);
