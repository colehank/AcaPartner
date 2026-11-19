export type SourceFormat='docx'|'latex';
export type Asset={sha:string;url:string;size:number;filename:string};
export type RenderRecord={object_id:string;revision:number;source_sha256:string;asset:string|{sha:string}};
export type NativeDocument={
  id:string;project_id:string;revision:number;title:string;
  source_state:{mode:'structured'|'latex'|'univer'|'docx'|'unselected'};
  sources:{latex:string;univer:unknown|null;docx:Asset|null};
  structured_blocks:{id:string;kind:string;text:string}[];
  render:RenderRecord|null;
  adapters:{docx:{editor:string;version:string;file_editing:boolean;max_bytes:number};latex:{compiler_available:boolean}};
};
export type Checkout={id:string;path:string;object_id:string;project_id:string;base_revision:number;source_sha256:string};
export const emptyLatex=String.raw`\documentclass{article}
\usepackage{amsmath}
\title{Research manuscript}
\begin{document}
\maketitle

\section{Research question}

\section{Methods}

\section{Results}

\section{Discussion}

\end{document}
`;
