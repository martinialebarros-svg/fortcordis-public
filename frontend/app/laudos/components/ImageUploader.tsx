"use client";

import React, { useState, useCallback, useEffect, useRef } from "react";
import { Upload, X, Loader2, MoveUp, MoveDown, GripVertical } from "lucide-react";
import api from "@/lib/axios";
import ImagePreviewModal from "./ImagePreviewModal";

interface Imagem {
  id: string;
  nome: string;
  descricao: string;
  ordem: number;
  dataUrl: string;
  tamanho: number;
  file?: File;
  serverId?: number;
  tempId?: number;
  uploaded: boolean;
  persisted?: boolean;
  incluirNoPdf?: boolean;
  requerReenvio?: boolean;
}

interface ImageUploaderProps {
  onImagensChange?: (imagens: Imagem[]) => void;
  sessionId: string;
  imagensIniciais?: Imagem[];
  onUploadStateChange?: (active: boolean) => void;
}

export default function ImageUploader({
  onImagensChange,
  sessionId,
  imagensIniciais = [],
  onUploadStateChange,
}: ImageUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [imagens, setImagens] = useState<Imagem[]>(imagensIniciais);
  const imagensAtuais = useRef<Imagem[]>(imagensIniciais);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);

  const gerarId = () => Math.random().toString(36).substring(2, 15);

  const atualizarImagens = (atualizacao: React.SetStateAction<Imagem[]>) => {
    const novasImagens = typeof atualizacao === "function"
      ? atualizacao(imagensAtuais.current)
      : atualizacao;
    imagensAtuais.current = novasImagens;
    setImagens(novasImagens);
    onImagensChange?.(novasImagens);
  };

  useEffect(() => {
    const iniciais = imagensIniciais.map((imagem) => ({
      ...imagem,
      incluirNoPdf: imagem.incluirNoPdf ?? true,
    }));
    imagensAtuais.current = iniciais;
    setImagens(iniciais);
  }, [imagensIniciais]);

  const persistirConfiguracaoTemporaria = async (lista: Imagem[]) => {
    const enviadas = lista.filter((imagem) => imagem.uploaded && imagem.tempId);
    if (enviadas.length === 0) return;
    try {
      await api.put(`/imagens/temp/session/${sessionId}/configuracao`, {
        imagens: enviadas.map((imagem) => ({
          id: imagem.tempId,
          ordem: imagem.ordem,
          incluir_no_pdf: imagem.incluirNoPdf ?? true,
          descricao: imagem.descricao,
        })),
      });
      setError(null);
    } catch (err) {
      console.error("Erro ao salvar configuração das imagens:", err);
      setError("Não foi possível salvar a ordem ou a seleção para o PDF. Tente novamente.");
    }
  };

  const fazerUploadImagem = async (
    imagem: Imagem
  ): Promise<{ success: boolean; tempId?: number }> => {
    if (!imagem.file || imagem.uploaded) return { success: true, tempId: imagem.tempId };
    
    try {
      const formData = new FormData();
      formData.append("arquivo", imagem.file);
      formData.append("ordem", imagem.ordem.toString());
      formData.append("descricao", imagem.descricao || "");
      formData.append("session_id", sessionId);
      formData.append("incluir_no_pdf", String(imagem.incluirNoPdf ?? true));
      
      const response = await api.post("/imagens/upload-temp", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });
      
      if (response.data && response.data.success) {
        return {
          success: true,
          tempId: response.data.imagem_id,
        };
      }
      return { success: false };
    } catch (err) {
      console.error("Erro ao fazer upload:", err);
      return { success: false };
    }
  };

  const processarArquivos = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    // Clearing the input or finishing a drop can invalidate the live FileList.
    const arquivos = Array.from(files);
    if (!sessionId) {
      setError("A sessão de imagens ainda está sendo preparada. Tente novamente em instantes.");
      return;
    }

    setUploading(true);
    onUploadStateChange?.(true);
    setError(null);

    const novasImagens: Imagem[] = [];

    for (const file of arquivos) {
      
      if (!file.type.startsWith("image/")) {
        setError(`Arquivo ${file.name} não é uma imagem válida`);
        continue;
      }

      if (file.size > 10 * 1024 * 1024) {
        setError(`Arquivo ${file.name} excede 10MB`);
        continue;
      }

      try {
        const dataUrl = await new Promise<string>((resolve) => {
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result as string);
          reader.readAsDataURL(file);
        });

        const novaImagem: Imagem = {
          id: gerarId(),
          nome: file.name,
          descricao: "",
          ordem: imagens.length + novasImagens.length,
          dataUrl,
          tamanho: file.size,
          file,
          uploaded: false,
          incluirNoPdf: true,
        };

        novasImagens.push(novaImagem);
      } catch (err) {
        console.error(`Erro ao processar ${file.name}:`, err);
      }
    }

    atualizarImagens((atuais) => [...atuais, ...novasImagens]);

    // Fazer upload das novas imagens
    for (const imagem of novasImagens) {
      const resultado = await fazerUploadImagem(imagem);
      if (resultado.success) {
        atualizarImagens((atuais) => atuais.map((img) =>
          img.id === imagem.id
            ? { ...img, uploaded: true, tempId: resultado.tempId }
            : img
        ));
      }
    }

    setUploading(false);
    onUploadStateChange?.(false);
  };

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    processarArquivos(e.dataTransfer.files);
  }, [imagens, sessionId]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    processarArquivos(e.target.files);
    e.target.value = "";
  }, [imagens, sessionId]);

  const removerImagem = async (id: string) => {
    const imagem = imagens.find(img => img.id === id);
    if (imagem?.persisted && imagem.serverId) {
      try {
        await api.delete(`/imagens/${imagem.serverId}`);
      } catch (e) {
        console.error("Erro ao remover imagem do laudo:", e);
      }
    } else if (imagem?.uploaded && imagem.tempId && sessionId) {
      try {
        await api.delete(`/imagens/temp/${imagem.tempId}?session_id=${sessionId}`);
      } catch (e) {
        console.error("Erro ao remover imagem do servidor:", e);
      }
    }
    
    const novasImagens = imagens
      .filter(img => img.id !== id)
      .map((img, idx) => ({ ...img, ordem: idx }));
    atualizarImagens(novasImagens);
    await persistirConfiguracaoTemporaria(novasImagens);
  };

  const moverImagemPara = async (index: number, newIndex: number) => {
    if (index === newIndex || index < 0 || newIndex < 0 || newIndex >= imagens.length) return;
    const novasImagens = [...imagens];
    const [movida] = novasImagens.splice(index, 1);
    novasImagens.splice(newIndex, 0, movida);
    const imagensReordenadas = novasImagens.map((img, i) => ({ ...img, ordem: i }));
    atualizarImagens(imagensReordenadas);
    await persistirConfiguracaoTemporaria(imagensReordenadas);
  };

  const moverImagem = (index: number, direcao: "up" | "down") => {
    if (direcao === "up" && index === 0) return;
    if (direcao === "down" && index === imagens.length - 1) return;
    void moverImagemPara(index, direcao === "up" ? index - 1 : index + 1);
  };

  const alternarInclusaoNoPdf = async (index: number) => {
    const novasImagens = imagens.map((imagem, atual) =>
      atual === index ? { ...imagem, incluirNoPdf: !(imagem.incluirNoPdf ?? true) } : imagem
    );
    atualizarImagens(novasImagens);
    await persistirConfiguracaoTemporaria(novasImagens);
  };

  const formatarTamanho = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  return (
    <div className="space-y-4">
      {/* Área de Drop */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`
          border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer
          ${isDragging 
            ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20" 
            : "border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500"
          }
        `}
      >
        <input
          type="file"
          accept="image/*"
          multiple
          onChange={handleFileInput}
          disabled={!sessionId || uploading}
          className="hidden"
          id="image-upload"
        />
        <label htmlFor="image-upload" className="cursor-pointer block">
          {!sessionId ? (
            <div className="flex flex-col items-center">
              <Loader2 className="h-10 w-10 text-blue-500 animate-spin mb-3" />
              <p className="text-sm text-gray-600">Preparando o envio das imagens...</p>
            </div>
          ) : uploading ? (
            <div className="flex flex-col items-center">
              <Loader2 className="h-10 w-10 text-blue-500 animate-spin mb-3" />
              <p className="text-sm text-gray-600">Enviando imagens...</p>
            </div>
          ) : (
            <div className="flex flex-col items-center">
              <Upload className="h-10 w-10 text-gray-400 mb-3" />
              <p className="text-sm font-medium text-gray-700 mb-1">
                Arraste imagens aqui ou clique para selecionar
              </p>
              <p className="text-xs text-gray-500">
                JPG, PNG, GIF até 10MB cada
              </p>
            </div>
          )}
        </label>
      </div>

      {error && (
        <div className="p-3 bg-red-100 border border-red-300 text-red-800 rounded-lg text-sm">
          {error}
        </div>
      )}

      {/* Lista de Imagens */}
      {imagens.length > 0 && (
        <div className="space-y-2">
          <h4 className="font-medium text-gray-700">
            Imagens ({imagens.length})
            {imagens.some(img => !img.uploaded) && (
              <span className="text-xs text-yellow-600 ml-2">
                (algumas ainda não foram enviadas)
              </span>
            )}
          </h4>
          
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {imagens.map((imagem, index) => (
              <div 
                key={imagem.id}
                draggable={imagem.uploaded && !uploading}
                onDragStart={(event) => {
                  setDraggedIndex(index);
                  event.dataTransfer.effectAllowed = "move";
                }}
                onDragEnd={() => setDraggedIndex(null)}
                onDragOver={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  event.dataTransfer.dropEffect = "move";
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  if (draggedIndex !== null) void moverImagemPara(draggedIndex, index);
                  setDraggedIndex(null);
                }}
                className={`relative group bg-white border rounded-lg overflow-hidden shadow-sm ${
                  draggedIndex === index ? "opacity-50 ring-2 ring-teal-500" : ""
                }`}
              >
                {/* Preview */}
                <div className="aspect-square bg-gray-100 relative">
                  {imagem.dataUrl ? <img
                    src={imagem.dataUrl}
                    alt={imagem.nome}
                    className="w-full h-full object-cover cursor-zoom-in"
                    onClick={() => setPreviewIndex(index)}
                    role="button"
                    tabIndex={0}
                    aria-label={`Ampliar ${imagem.nome}`}
                    draggable={false}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setPreviewIndex(index);
                      }
                    }}
                  /> : <div className="flex h-full items-center justify-center p-3 text-center text-xs text-gray-600">
                    {imagem.requerReenvio ? "Reenvie este arquivo" : "Prévia indisponível"}
                  </div>}
                  
                  {/* Número da ordem */}
                  <div className="absolute top-2 left-2 bg-teal-600 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center">
                    {index + 1}
                  </div>
                  <div className="absolute bottom-2 left-2 rounded bg-black/65 p-1 text-white" title="Arraste para reordenar">
                    <GripVertical className="h-4 w-4" />
                  </div>

                  {/* Status de upload */}
                    {!imagem.uploaded && (
                      <div className="absolute top-2 right-2 bg-yellow-500 text-white text-xs px-2 py-1 rounded">
                        {imagem.requerReenvio ? "Reenviar" : "Enviando..."}
                      </div>
                    )}
                    {imagem.persisted && (
                      <div className="absolute top-2 right-2 bg-emerald-600 text-white text-xs px-2 py-1 rounded">
                        Salva
                      </div>
                    )}
                  
                  {/* Controles posicionados fora do centro clicável da miniatura */}
                  <div className="absolute bottom-2 right-2 flex gap-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                    <button
                      onClick={() => moverImagem(index, "up")}
                      disabled={index === 0 || uploading}
                      className="p-2 bg-white rounded-full hover:bg-gray-100 disabled:opacity-50"
                      title="Mover para cima"
                    >
                      <MoveUp className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => moverImagem(index, "down")}
                      disabled={index === imagens.length - 1 || uploading}
                      className="p-2 bg-white rounded-full hover:bg-gray-100 disabled:opacity-50"
                      title="Mover para baixo"
                    >
                      <MoveDown className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => removerImagem(imagem.id)}
                      className="p-2 bg-red-500 text-white rounded-full hover:bg-red-600"
                      title="Remover"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                
                {/* Info */}
                <div className="p-2">
                  <p className="text-xs text-gray-600 truncate" title={imagem.nome}>
                    {imagem.nome}
                  </p>
                  <p className="text-xs text-gray-400">
                    {formatarTamanho(imagem.tamanho)}
                  </p>
                  <label className="mt-2 block text-xs font-medium text-gray-700">
                    Legenda opcional no PDF
                    <input
                      type="text"
                      value={imagem.descricao}
                      maxLength={160}
                      onChange={(event) => atualizarImagens(imagens.map((item) =>
                        item.id === imagem.id ? { ...item, descricao: event.target.value } : item
                      ))}
                      onBlur={() => void persistirConfiguracaoTemporaria(imagens)}
                      placeholder="Ex.: Doppler da regurgitação tricúspide"
                      aria-label={`Legenda da imagem ${index + 1}`}
                      className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-xs text-gray-900"
                    />
                  </label>
                  <label className="mt-2 flex items-center gap-2 text-xs font-medium text-gray-700">
                    <input
                      type="checkbox"
                      checked={imagem.incluirNoPdf ?? true}
                      disabled={!imagem.uploaded || uploading}
                      onChange={() => void alternarInclusaoNoPdf(index)}
                      className="h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                    />
                    Incluir no PDF
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      <ImagePreviewModal
        images={imagens.map((imagem) => ({
          id: imagem.id,
          nome: imagem.nome,
          src: imagem.dataUrl,
        }))}
        selectedIndex={previewIndex}
        onSelectedIndexChange={setPreviewIndex}
      />
    </div>
  );
}
