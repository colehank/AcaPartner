import { defineConfig } from 'vite';
export default defineConfig({base:'/workdesk/',build:{outDir:'../../build/frontend/workdesk',emptyOutDir:true,license:{fileName:'THIRD_PARTY_LICENSES.md'}},server:{host:'127.0.0.1',proxy:{'/api':'http://127.0.0.1:8910'}}});
