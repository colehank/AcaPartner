import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';
export default defineConfig({base:'/workdesk/',plugins:[viteStaticCopy({targets:[
  {src:'node_modules/pdfjs-dist/cmaps/*',dest:'pdfjs/cmaps',rename:{stripBase:true}},
  {src:'node_modules/pdfjs-dist/standard_fonts/*',dest:'pdfjs/standard_fonts',rename:{stripBase:true}},
]})],build:{outDir:'../research_partner/web/workdesk',emptyOutDir:true,license:{fileName:'THIRD_PARTY_LICENSES.md'},rollupOptions:{input:{main:new URL('./index.html',import.meta.url).pathname,editors:new URL('./editors.html',import.meta.url).pathname}}},server:{host:'127.0.0.1',proxy:{'/api':'http://127.0.0.1:8910'}}});
