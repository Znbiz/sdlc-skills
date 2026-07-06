import { defineConfig } from 'orval';

const componentsSettings = {
  schemas: {
    suffix: 'DTO',
  },
  responses: {
    suffix: 'Response',
  },
  parameters: {
    suffix: 'Params',
  },
  requestBodies: {
    suffix: 'Bodies',
  },
};

export default defineConfig({
  primaryApi: {
    input: {
      target: '{{OPENAPI_PRIMARY_URL}}',
      filters: {
        mode: 'exclude',
        tags: ['{{EXCLUDED_TAG}}'],
      },
    },
    output: {
      clean: true,
      target: './src/shared/api/services/@generated/primaryApi.ts',
      override: {
        mutator: {
          path: './src/shared/api/client.ts',
          name: 'primaryApiRequest',
        },
        components: componentsSettings,
      },
    },
  },
  secondaryApi: {
    input: {
      target: '{{OPENAPI_SECONDARY_URL}}',
      filters: {
        tags: ['{{INCLUDED_TAG}}'],
      },
    },
    output: {
      target: './src/shared/api/services/@generated/secondaryApi.ts',
      override: {
        mutator: {
          path: './src/shared/api/client.ts',
          name: 'secondaryApiRequest',
        },
        components: componentsSettings,
      },
    },
  },
});
