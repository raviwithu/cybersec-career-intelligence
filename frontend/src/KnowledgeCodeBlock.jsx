import { Highlight, themes } from "prism-react-renderer";

// Syntax highlighting renders tokens as React text nodes. Code is never evaluated or inserted as HTML.
// prism-react-renderer bundles no grammar for some allowed languages; those use a close grammar or plain text.
const GRAMMARS = { java: "clike", csharp: "clike", php: "clike", ruby: "plain", bash: "plain", http: "plain" };

export default function KnowledgeCodeBlock({ code, language }) {
  return <Highlight code={code} language={GRAMMARS[language] || language} theme={themes.vsDark}>
    {({ className, style, tokens, getLineProps, getTokenProps }) => <pre className={`kc-code ${className}`} style={style}><code>{tokens.map((line, lineIndex) => <span key={lineIndex} {...getLineProps({ line })}>{line.map((token, tokenIndex) => <span key={tokenIndex} {...getTokenProps({ token })} />)}{"\n"}</span>)}</code></pre>}
  </Highlight>;
}
