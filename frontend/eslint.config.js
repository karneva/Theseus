import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      // 타입 정보를 쓰는 규칙(floating promise, unsafe any 등)까지 켠다.
      tseslint.configs.recommendedTypeChecked,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // 처리되지 않은 Promise는 오류가 조용히 사라지므로 await/void/catch 중 하나를 강제한다.
      '@typescript-eslint/no-floating-promises': 'error',
      // 디버그용 console.log가 남지 않게 한다. 운영 진단용 warn/error는 허용한다.
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  {
    // JSX 이벤트 핸들러에 async 함수를 넘기는 패턴은 React가 반환값을 쓰지 않으므로 허용한다.
    files: ['**/*.tsx'],
    rules: {
      '@typescript-eslint/no-misused-promises': [
        'error',
        { checksVoidReturn: { attributes: false } },
      ],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    rules: {
      // 테스트에서는 vi.fn/expect.any 등 매처가 any를 다루는 경우가 많다.
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/unbound-method': 'off',
    },
  },
]);
