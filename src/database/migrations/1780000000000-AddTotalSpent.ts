import { MigrationInterface, QueryRunner } from 'typeorm';

export class AddTotalSpent1780000000000 implements MigrationInterface {
  name = 'AddTotalSpent1780000000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "total_spent" integer NOT NULL DEFAULT 0`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "total_spent"`,
    );
  }
}
