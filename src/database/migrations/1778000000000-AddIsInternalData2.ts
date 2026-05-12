import { MigrationInterface, QueryRunner } from 'typeorm';

export class AddIsInternalData21778000000000 implements MigrationInterface {
  name = 'AddIsInternalData21778000000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "is_internal_data2" boolean NOT NULL DEFAULT false`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "is_internal_data2"`,
    );
  }
}
