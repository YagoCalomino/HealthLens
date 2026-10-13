import { useQuery } from '@tanstack/react-query';

export interface CidCodigo {
  id: string;
  descricao: string;
}

export interface CidGrupo {
  id: string;
  descricao: string;
  codigos: CidCodigo[];
}

export interface CidCapitulo {
  id: string;
  descricao: string;
  grupos: CidGrupo[];
}

export interface CidHierarchy {
  capitulos: CidCapitulo[];
}

interface UseCidHierarchyResult {
  capitulos: CidCapitulo[];
  isLoading: boolean;
  isError: boolean;
}

async function fetchCidHierarchy(): Promise<CidHierarchy> {
  const res = await fetch('/cid10_hierarchy.json');
  if (!res.ok) {
    throw new Error(`Failed to fetch CID-10 hierarchy: ${res.status}`);
  }
  return res.json() as Promise<CidHierarchy>;
}

export function useCidHierarchy(): UseCidHierarchyResult {
  const { data, isLoading, isError } = useQuery<CidHierarchy>({
    queryKey: ['cid10'],
    queryFn: fetchCidHierarchy,
    staleTime: Infinity, // Static reference data — never re-fetch during session
  });

  return {
    capitulos: data?.capitulos ?? [],
    isLoading,
    isError,
  };
}
