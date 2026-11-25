# Desenvolvido por João Sipraki

# Perfil Geoecológico Adaptável — 17.23.2 experimental

O complemento gera perfis com faixas temáticas que o usuário escolhe para cada estudo. Esta versão foi testada somente no **QGIS 3.44.13 para Windows**. Não há dependências Python externas além das distribuídas com QGIS. Licença: GPL-3.0-or-later. Desenvolvido por João Sipraki; projeto pessoal e independente. Consulte COPYING e NOTICE.md.

## Instalação por ZIP

1. No QGIS 3.44.13, abra **Complementos → Gerenciar e Instalar Complementos → Instalar a partir do ZIP**.
2. Selecione `Perfil_Geoecologico_Adaptavel_17.23.2.zip` e instale.
3. Acesse **Complementos → Perfil Geoecológico Adaptável** para abrir o assistente, criar um perfil ou pré-verificar entradas.

## Primeiro uso

Use o conjunto `Demonstracao_Sintetica` que acompanha a distribuição, não camadas de um projeto de produção. Abra `projeto_demo.qgz`, escolha a linha A–B, o MDE e duas faixas demonstrativas (uma poligonal e uma raster), execute a pré-verificação e então gere o perfil. Use nomes de layout e GeoPackage novos. No resultado, abra o layout pelo Gerenciador de Layouts e exporte para PNG ou PDF.

O projeto e os caminhos relativos devem continuar válidos se toda a pasta da demonstração for copiada para outro local. O roteiro explica como recriar os dados sintéticos e quais valores esperar.

## Entradas próprias

- **Linha A–B:** uma feição linear aberta, válida, com SRC real atribuído. Atribuir SRC não transforma coordenadas.
- **MDE:** raster válido com SRC e NoData definidos. Declare a unidade vertical apenas quando souber se os valores são metros, pés ou outro fator. A ferramenta não determina datum vertical nem valida cotas cientificamente.
- **Faixa vetorial:** campo de classe escolhido e simbologia categorizada visível ou QML aplicável. Polígonos são corrigidos em uma cópia temporária para o processamento; as fontes não são sobrescritas. A verificação relata geometrias que continuarem inválidas.
- **Faixa raster:** banda selecionada. Pode usar limites e rótulos manuais ou classes automáticas calculadas pelas amostras ao longo da linha.
- **Opcionais:** rios, núcleo urbano e mapa de localização. Eles podem ser omitidos.

## Classes e cores

Os modos de intervalos iguais e quantis são relativos às amostras válidas ao longo do perfil; outro transecto pode obter limites diferentes. Use a classificação manual quando precisar manter uma escala fixa entre perfis. Informe limites, rótulos e cores com base no método do estudo. O complemento não interpreta o significado ambiental nem escolhe uma paleta pelo título.

No modo automático de SRC, a ferramenta consulta a área de uso publicada do CRS. Se a linha estiver fora dela, é usada uma cópia transformada para um SRC métrico local e a escolha aparece no log. Se não for possível confirmar a área do SRC métrico de entrada, escolha explicitamente o SRC de análise. Uma seleção manual é mantida e avisada quando estiver fora da área publicada. As fontes originais não têm seu SRC alterado.

## Saídas e diagnóstico

A geração escreve camadas no GeoPackage indicado e cria um layout no projeto. Exporte PNG/PDF pelo layout. A pré-verificação não gera arquivo. Leia o log para cobertura, lacunas, sobreposições, geometrias inválidas, SRC, cotas sem dado e limites de classificação. Reparos e reprojeções de entrada ocorrem em cópias temporárias; isso não recupera todas as falhas nem substitui revisão dos dados.

Se encontrar um erro, registre versão do QGIS, versão do complemento, passos para reproduzir, parâmetros e log. Evite compartilhar fontes de terceiros ou dados pessoais sem autorização.


## Crédito e licença

Desenvolvido por João Sipraki. Copyright (C) 2026 João Sipraki. Licenciado sob GPL-3.0-or-later; consulte COPYING e NOTICE.md. O projeto é pessoal e independente.
